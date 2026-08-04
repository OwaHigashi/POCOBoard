"""DirectShow camera capture via raw ctypes COM — no third-party deps.

Why this exists
---------------
Qt 6 enumerates cameras through Windows Media Foundation.  MF only sees
devices registered under the modern camera categories — it does NOT see
driver-based / filter-based virtual webcams that register only the
legacy DirectShow / KS video categories: ManyCam Virtual Webcam, OBS
Virtual Camera, NVIDIA Broadcast, Insta360 Virtual Camera, ...  Those
outputs are perfectly normal DirectShow capture sources, so POCOBoard
captures them here with a DirectShow FilterGraph driven directly
through ctypes COM (same no-pip-deps philosophy as midi_engine.py's
winmm binding).

Renderer choice: VMR9, not SampleGrabber
----------------------------------------
The classic capture recipe (SampleGrabber + NullRenderer from
qedit.dll) is DEAD on current Windows 11 builds: qedit.dll still ships
but no longer contains those classes — CoCreateInstance fails with
REGDB_E_CLASSNOTREG and even a direct DllGetClassObject returns
CLASS_E_CLASSNOTAVAILABLE (verified on build 26200).  Instead we render
the stream into a windowless VMR9 (Video Mixing Renderer 9, quartz.dll
— the same DLL that provides FilterGraph itself, so it cannot be
missing) whose clipping window is a small hidden widget, and poll
IVMRWindowlessControl9::GetCurrentImage for frames.  Verified on this
setup: frames keep updating with the window hidden, first frame lands
in ~50 ms, and a grab costs ~1 ms at 640x480 / a few ms at 1080p.

* `list_dshow_cameras()` returns `(moniker_display_name,
  friendly_name)` pairs; the moniker display name is the stable id.
* `DShowCamera.open(moniker_name)` binds the source filter and builds
  source → VMR9(windowless).  `grab()` copies the newest frame as a
  QImage.  Polling happens from the caller (DisplayWindow's tick), so
  the caller can skip grabs while the camera is occluded.
* GetCurrentImage hands back a bottom-up 32-bpp DIB in CoTaskMem —
  byte-identical to QImage Format_RGB32 after a vertical flip.
"""
from __future__ import annotations
import ctypes
from ctypes import POINTER, byref, c_long, c_ulong, c_void_p, c_wchar_p
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

_ole32    = ctypes.windll.ole32
_oleaut32 = ctypes.windll.oleaut32

_CLSCTX_INPROC_SERVER = 0x1
_S_OK = 0


class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort),
                ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]

    def __init__(self, s: str = "") -> None:
        super().__init__()
        if s:
            _ole32.CLSIDFromString(c_wchar_p(s), byref(self))


_CLSID_SystemDeviceEnum   = _GUID("{62BE5D10-60EB-11d0-BD3B-00A0C911CE86}")
_IID_ICreateDevEnum       = _GUID("{29840822-5B84-11D0-BD3B-00A0C911CE86}")
_CLSID_VideoInputCategory = _GUID("{860BB310-5D01-11d0-BD3B-00A0C911CE86}")
_IID_IPropertyBag         = _GUID("{55272A00-42CB-11CE-8135-00AA004BB851}")

_CLSID_FilterGraph          = _GUID("{E436EBB3-524F-11CE-9F53-0020AF0BA770}")
_IID_IGraphBuilder          = _GUID("{56A868A9-0AD4-11CE-B03A-0020AF0BA770}")
_CLSID_CaptureGraphBuilder2 = _GUID("{BF87B6E1-8C27-11D0-B3F0-00AA003761C5}")
_IID_ICaptureGraphBuilder2  = _GUID("{93E5A4E0-2D50-11D2-ABFA-00A0C9C6E38D}")
_IID_IBaseFilter            = _GUID("{56A86895-0AD4-11CE-B03A-0020AF0BA770}")
_IID_IMediaControl          = _GUID("{56A868B1-0AD4-11CE-B03A-0020AF0BA770}")

_CLSID_VMR9                 = _GUID("{51B4ABF3-748F-4E3B-A276-C828330E926A}")
_IID_IVMRFilterConfig9      = _GUID("{5A804648-4F66-4867-9C43-4F5C822CF1B8}")
_IID_IVMRWindowlessControl9 = _GUID("{8F537D09-F85E-4414-B23B-502E54C79927}")
_VMR9Mode_Windowless = 2

_PIN_CATEGORY_CAPTURE = _GUID("{FB6C4281-0353-11D1-905F-0000C0CC16BA}")
_MEDIATYPE_Video      = _GUID("{73646976-0000-0010-8000-00AA00389B71}")


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


class _VARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort),
                ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("val", c_void_p), ("pad", c_void_p)]


def _com(ptr: c_void_p, slot: int, argtypes: list, *args) -> int:
    """Call vtable slot `slot` on COM interface `ptr`; returns HRESULT."""
    vtbl = ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(c_long, c_void_p, *argtypes)(vtbl[slot])
    return fn(ptr, *args)


def _release(ptr: Optional[c_void_p]) -> None:
    if ptr:
        vtbl = ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents
        ctypes.WINFUNCTYPE(c_ulong, c_void_p)(vtbl[2])(ptr)


def _co_init() -> None:
    # S_OK / S_FALSE / RPC_E_CHANGED_MODE are all fine — Qt has usually
    # initialized COM (STA) on the GUI thread already.
    _ole32.CoInitialize(None)


def _create(clsid: _GUID, iid: _GUID) -> c_void_p:
    obj = c_void_p()
    hr = _ole32.CoCreateInstance(byref(clsid), None, _CLSCTX_INPROC_SERVER,
                                 byref(iid), byref(obj))
    if hr != _S_OK or not obj:
        raise OSError(f"CoCreateInstance failed hr={hr & 0xFFFFFFFF:#010x}")
    return obj


def _moniker_display_name(moniker: c_void_p) -> str:
    bind_ctx = c_void_p()
    if _ole32.CreateBindCtx(0, byref(bind_ctx)) != _S_OK:
        return ""
    name_ptr = c_void_p()
    # IMoniker::GetDisplayName — vtable slot 20.
    hr = _com(moniker, 20, [c_void_p, c_void_p, POINTER(c_void_p)],
              bind_ctx, None, byref(name_ptr))
    out = ""
    if hr == _S_OK and name_ptr:
        out = ctypes.wstring_at(name_ptr)
        _ole32.CoTaskMemFree(name_ptr)
    _release(bind_ctx)
    return out


def _moniker_friendly_name(moniker: c_void_p) -> str:
    bag = c_void_p()
    # IMoniker::BindToStorage — vtable slot 9.
    hr = _com(moniker, 9, [c_void_p, c_void_p, c_void_p, POINTER(c_void_p)],
              None, None, byref(_IID_IPropertyBag), byref(bag))
    if hr != _S_OK or not bag:
        return ""
    var = _VARIANT()
    var.vt = 8  # VT_BSTR
    # IPropertyBag::Read — vtable slot 3.
    hr = _com(bag, 3, [c_wchar_p, POINTER(_VARIANT), c_void_p],
              "FriendlyName", byref(var), None)
    out = ""
    if hr == _S_OK and var.val:
        out = ctypes.wstring_at(var.val)
        _oleaut32.VariantClear(byref(var))
    _release(bag)
    return out


def _enum_video_monikers():
    """Yield IMoniker pointers for every DirectShow video-input device.
    The caller must _release() each yielded moniker."""
    dev_enum = _create(_CLSID_SystemDeviceEnum, _IID_ICreateDevEnum)
    try:
        enum_mk = c_void_p()
        # ICreateDevEnum::CreateClassEnumerator — slot 3.  S_FALSE (1)
        # means the category is empty.
        hr = _com(dev_enum, 3, [c_void_p, POINTER(c_void_p), ctypes.c_uint32],
                  byref(_CLSID_VideoInputCategory), byref(enum_mk), 0)
        if hr != _S_OK or not enum_mk:
            return
        try:
            while True:
                mk = c_void_p()
                fetched = c_ulong(0)
                # IEnumMoniker::Next — slot 3.
                hr = _com(enum_mk, 3,
                          [c_ulong, POINTER(c_void_p), POINTER(c_ulong)],
                          1, byref(mk), byref(fetched))
                if hr != _S_OK or not fetched.value:
                    break
                yield mk
        finally:
            _release(enum_mk)
    finally:
        _release(dev_enum)


def list_dshow_cameras() -> list[tuple[str, str]]:
    """Return [(moniker_display_name, friendly_name)] for every
    DirectShow video-input device.  Never raises — a COM failure just
    yields an empty list (the Qt camera path is unaffected)."""
    out: list[tuple[str, str]] = []
    try:
        _co_init()
        for mk in _enum_video_monikers():
            try:
                name = _moniker_friendly_name(mk)
                ident = _moniker_display_name(mk)
                if name and ident:
                    out.append((ident, name))
            finally:
                _release(mk)
    except Exception as exc:
        print(f"[dshow] enumeration failed: {exc!r}")
    return out


class DShowCamera:
    """One open DirectShow capture device delivering QImages via grab().

    Must be used from the Qt GUI thread (it owns a hidden QWidget for
    the VMR9 clipping window, and COM STA rules apply)."""

    def __init__(self) -> None:
        self._graph:   Optional[c_void_p] = None
        self._builder: Optional[c_void_p] = None
        self._source:  Optional[c_void_p] = None
        self._vmr9:    Optional[c_void_p] = None
        self._wc9:     Optional[c_void_p] = None    # IVMRWindowlessControl9
        self._control: Optional[c_void_p] = None
        self._host = None                            # hidden QWidget (clipping hwnd)
        self.description = ""

    # ---------- lifecycle ----------
    def open(self, moniker_name: str) -> bool:
        self.close()
        try:
            _co_init()
            source = None
            for mk in _enum_video_monikers():
                try:
                    if _moniker_display_name(mk) == moniker_name:
                        obj = c_void_p()
                        # IMoniker::BindToObject — slot 8.
                        hr = _com(mk, 8,
                                  [c_void_p, c_void_p, c_void_p, POINTER(c_void_p)],
                                  None, None, byref(_IID_IBaseFilter), byref(obj))
                        if hr == _S_OK and obj:
                            source = obj
                            self.description = _moniker_friendly_name(mk)
                finally:
                    _release(mk)
                if source is not None:
                    break
            if source is None:
                print(f"[dshow] device not found: {moniker_name!r}")
                return False
            self._source = source
            self._build_graph()
            return True
        except Exception as exc:
            print(f"[dshow] open failed: {exc!r}")
            self.close()
            return False

    def _build_graph(self) -> None:
        assert self._source is not None
        from PySide6.QtWidgets import QWidget
        # Never shown — VMR9 windowless mode just needs a valid HWND to
        # clip against.  Frame delivery keeps running while it's hidden
        # (verified with ManyCam + a real USB cam on this machine).
        self._host = QWidget()
        self._host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self._host.resize(16, 16)
        hwnd = int(self._host.winId())

        self._graph = _create(_CLSID_FilterGraph, _IID_IGraphBuilder)
        self._builder = _create(_CLSID_CaptureGraphBuilder2,
                                _IID_ICaptureGraphBuilder2)
        # ICaptureGraphBuilder2::SetFiltergraph — slot 3.
        hr = _com(self._builder, 3, [c_void_p], self._graph)
        if hr != _S_OK:
            raise OSError(f"SetFiltergraph hr={hr:#x}")
        # IFilterGraph::AddFilter — slot 3.
        hr = _com(self._graph, 3, [c_void_p, c_wchar_p], self._source, "src")
        if hr != _S_OK:
            raise OSError(f"AddFilter(src) hr={hr:#x}")

        self._vmr9 = _create(_CLSID_VMR9, _IID_IBaseFilter)
        cfg = c_void_p()
        # IUnknown::QueryInterface — slot 0.
        hr = _com(self._vmr9, 0, [c_void_p, POINTER(c_void_p)],
                  byref(_IID_IVMRFilterConfig9), byref(cfg))
        if hr != _S_OK or not cfg:
            raise OSError(f"QI(IVMRFilterConfig9) hr={hr:#x}")
        try:
            # IVMRFilterConfig9::SetRenderingMode — slot 8.
            hr = _com(cfg, 8, [ctypes.c_uint32], _VMR9Mode_Windowless)
            if hr != _S_OK:
                raise OSError(f"SetRenderingMode hr={hr:#x}")
        finally:
            _release(cfg)
        wc = c_void_p()
        hr = _com(self._vmr9, 0, [c_void_p, POINTER(c_void_p)],
                  byref(_IID_IVMRWindowlessControl9), byref(wc))
        if hr != _S_OK or not wc:
            raise OSError(f"QI(IVMRWindowlessControl9) hr={hr:#x}")
        self._wc9 = wc
        # IVMRWindowlessControl9::SetVideoClippingWindow — slot 10.
        hr = _com(self._wc9, 10, [c_void_p], hwnd)
        if hr != _S_OK:
            raise OSError(f"SetVideoClippingWindow hr={hr:#x}")

        hr = _com(self._graph, 3, [c_void_p, c_wchar_p], self._vmr9, "vmr9")
        if hr != _S_OK:
            raise OSError(f"AddFilter(vmr9) hr={hr:#x}")

        # ICaptureGraphBuilder2::RenderStream — slot 7:
        # (pCategory, pType, pSource, pfCompressor, pfRenderer)
        hr = _com(self._builder, 7,
                  [c_void_p, c_void_p, c_void_p, c_void_p, c_void_p],
                  byref(_PIN_CATEGORY_CAPTURE), byref(_MEDIATYPE_Video),
                  self._source, None, self._vmr9)
        if hr not in (0, 1):
            # Some sources expose only a preview pin — retry uncategorized.
            hr = _com(self._builder, 7,
                      [c_void_p, c_void_p, c_void_p, c_void_p, c_void_p],
                      None, byref(_MEDIATYPE_Video),
                      self._source, None, self._vmr9)
        if hr not in (0, 1):
            raise OSError(f"RenderStream hr={hr & 0xFFFFFFFF:#010x}")

        control = c_void_p()
        hr = _com(self._graph, 0, [c_void_p, POINTER(c_void_p)],
                  byref(_IID_IMediaControl), byref(control))
        if hr != _S_OK or not control:
            raise OSError(f"QI(IMediaControl) hr={hr:#x}")
        self._control = control
        # IMediaControl::Run — slot 7 (S_FALSE = still cueing, fine).
        hr = _com(self._control, 7, [])
        if hr not in (0, 1):
            raise OSError(f"Run hr={hr & 0xFFFFFFFF:#010x}")
        print(f"[dshow] started: {self.description}")

    def is_open(self) -> bool:
        return self._control is not None

    def grab(self) -> Optional[QImage]:
        """Copy the newest frame; None until the first frame lands."""
        if self._wc9 is None:
            return None
        dib = c_void_p()
        # IVMRWindowlessControl9::GetCurrentImage — slot 13.  Returns a
        # packed DIB (BITMAPINFOHEADER + bits) in CoTaskMem.
        hr = _com(self._wc9, 13, [POINTER(c_void_p)], byref(dib))
        if hr != _S_OK or not dib:
            return None
        try:
            bih = ctypes.cast(dib, POINTER(_BITMAPINFOHEADER)).contents
            w, h, bpp = bih.biWidth, bih.biHeight, bih.biBitCount
            if w <= 0 or h == 0 or bpp != 32:
                return None
            stride = w * 4
            buf = ctypes.string_at(dib.value + bih.biSize, stride * abs(h))
        finally:
            _ole32.CoTaskMemFree(dib)
        img = QImage(buf, w, abs(h), stride, QImage.Format.Format_RGB32)
        if h > 0:
            # Positive height = bottom-up DIB → flip to top-down.
            flipped = getattr(img, "flipped", None)
            if flipped is not None:
                return flipped(Qt.Orientation.Vertical)
            return img.mirrored(False, True)
        return img.copy()

    def close(self) -> None:
        if self._control is not None:
            try:
                # IMediaControl::Stop — slot 9.
                _com(self._control, 9, [])
            except Exception:
                pass
        for attr in ("_control", "_wc9", "_vmr9", "_source",
                     "_builder", "_graph"):
            _release(getattr(self, attr))
            setattr(self, attr, None)
        if self._host is not None:
            self._host.deleteLater()
            self._host = None
        self.description = ""
