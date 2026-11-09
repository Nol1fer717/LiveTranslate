"""On-demand suggestions from the Windows Spell Checking API."""
import ctypes
import os
import uuid


def suggestions(word):
    if os.name != 'nt' or not word or len(word) > 80:
        return []
    language = 'ru-RU' if any('\u0400' <= char <= '\u04ff' for char in word) else 'en-US'
    ole = ctypes.windll.ole32
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    ole.CoCreateInstance.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    clsid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID('7ab36653-1796-484b-bdfa-e74f1db7c1dc').bytes_le)
    iid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID('8e018a9d-2415-4677-bf08-794ea61f94bb').bytes_le)
    status = ole.CoInitializeEx(None, 2)
    initialized = status in (0, 1)
    if status not in (0, 1, -2147417850):
        return []
    ptr = ctypes.c_void_p
    factory, checker, errors, error, enum = (ptr() for _ in range(5))

    def call(obj, index, args, *values):
        table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ptr))).contents
        method = ctypes.WINFUNCTYPE(ctypes.c_long, ptr, *args)(table[index])
        return method(obj, *values)

    def release(obj):
        if obj.value:
            call(obj, 2, [])

    try:
        if ole.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(factory)) < 0:
            return []
        if call(factory, 5, [ctypes.c_wchar_p, ctypes.POINTER(ptr)], language, ctypes.byref(checker)) < 0:
            return []
        if call(checker, 4, [ctypes.c_wchar_p, ctypes.POINTER(ptr)], word, ctypes.byref(errors)) < 0:
            return []
        if call(errors, 3, [ctypes.POINTER(ptr)], ctypes.byref(error)) != 0 or not error.value:
            return []
        if call(checker, 5, [ctypes.c_wchar_p, ctypes.POINTER(ptr)], word, ctypes.byref(enum)) < 0:
            return []
        result = []
        for _ in range(5):
            value, fetched = ptr(), ctypes.c_ulong()
            hr = call(enum, 3, [ctypes.c_ulong, ctypes.POINTER(ptr), ctypes.POINTER(ctypes.c_ulong)], 1, ctypes.byref(value), ctypes.byref(fetched))
            if hr != 0 or not value.value:
                break
            try:
                result.append(ctypes.wstring_at(value.value))
            finally:
                ole.CoTaskMemFree(value)
        return result
    finally:
        for item in (enum, error, errors, checker, factory):
            release(item)
        if initialized:
            ole.CoUninitialize()
