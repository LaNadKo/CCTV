"""Helpers for byte-reproducible Processor PyInstaller artifacts."""
from __future__ import annotations

import io
import struct
import zipfile
import zlib
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader
from PyInstaller.archive.writers import CArchiveWriter
from PyInstaller.utils.win32 import winutils


# PE timestamps recovered from the final verified portable artifacts.
RUNTIME_BUILD_TIMESTAMP = 1780942229
SUPERVISOR_BUILD_TIMESTAMP = 1780942528


SUPERVISOR_BASE_LIBRARY_ORDER = (
    "traceback.pyc",
    "heapq.pyc",
    "enum.pyc",
    "re/_parser.pyc",
    "re/_constants.pyc",
    "re/_compiler.pyc",
    "re/_casefix.pyc",
    "re/__init__.pyc",
    "locale.pyc",
    "functools.pyc",
    "stat.pyc",
    "collections/abc.pyc",
    "collections/__init__.pyc",
    "sre_constants.pyc",
    "io.pyc",
    "types.pyc",
    "abc.pyc",
    "ntpath.pyc",
    "weakref.pyc",
    "operator.pyc",
    "keyword.pyc",
    "sre_compile.pyc",
    "codecs.pyc",
    "_weakrefset.pyc",
    "genericpath.pyc",
    "posixpath.pyc",
    "reprlib.pyc",
    "warnings.pyc",
    "sre_parse.pyc",
    "_collections_abc.pyc",
    "encodings/zlib_codec.pyc",
    "encodings/uu_codec.pyc",
    "encodings/utf_8_sig.pyc",
    "encodings/utf_8.pyc",
    "encodings/utf_7.pyc",
    "encodings/utf_32_le.pyc",
    "encodings/utf_32_be.pyc",
    "encodings/utf_32.pyc",
    "encodings/utf_16_le.pyc",
    "encodings/utf_16_be.pyc",
    "encodings/utf_16.pyc",
    "encodings/unicode_escape.pyc",
    "encodings/undefined.pyc",
    "encodings/tis_620.pyc",
    "encodings/shift_jisx0213.pyc",
    "encodings/shift_jis_2004.pyc",
    "encodings/shift_jis.pyc",
    "encodings/rot_13.pyc",
    "encodings/raw_unicode_escape.pyc",
    "encodings/quopri_codec.pyc",
    "encodings/punycode.pyc",
    "encodings/ptcp154.pyc",
    "encodings/palmos.pyc",
    "encodings/oem.pyc",
    "encodings/mbcs.pyc",
    "encodings/mac_turkish.pyc",
    "encodings/mac_romanian.pyc",
    "encodings/mac_roman.pyc",
    "encodings/mac_latin2.pyc",
    "encodings/mac_iceland.pyc",
    "encodings/mac_greek.pyc",
    "encodings/mac_farsi.pyc",
    "encodings/mac_cyrillic.pyc",
    "encodings/mac_croatian.pyc",
    "encodings/mac_arabic.pyc",
    "encodings/latin_1.pyc",
    "encodings/kz1048.pyc",
    "encodings/koi8_u.pyc",
    "encodings/koi8_t.pyc",
    "encodings/koi8_r.pyc",
    "encodings/johab.pyc",
    "encodings/iso8859_9.pyc",
    "encodings/iso8859_8.pyc",
    "encodings/iso8859_7.pyc",
    "encodings/iso8859_6.pyc",
    "encodings/iso8859_5.pyc",
    "encodings/iso8859_4.pyc",
    "encodings/iso8859_3.pyc",
    "encodings/iso8859_2.pyc",
    "encodings/iso8859_16.pyc",
    "encodings/iso8859_15.pyc",
    "encodings/iso8859_14.pyc",
    "encodings/iso8859_13.pyc",
    "encodings/iso8859_11.pyc",
    "encodings/iso8859_10.pyc",
    "encodings/iso8859_1.pyc",
    "encodings/iso2022_kr.pyc",
    "encodings/iso2022_jp_ext.pyc",
    "encodings/iso2022_jp_3.pyc",
    "encodings/iso2022_jp_2004.pyc",
    "encodings/iso2022_jp_2.pyc",
    "encodings/iso2022_jp_1.pyc",
    "encodings/iso2022_jp.pyc",
    "encodings/idna.pyc",
    "encodings/hz.pyc",
    "encodings/hp_roman8.pyc",
    "encodings/hex_codec.pyc",
    "encodings/gbk.pyc",
    "encodings/gb2312.pyc",
    "encodings/gb18030.pyc",
    "encodings/euc_kr.pyc",
    "encodings/euc_jp.pyc",
    "encodings/euc_jisx0213.pyc",
    "encodings/euc_jis_2004.pyc",
    "encodings/cp950.pyc",
    "encodings/cp949.pyc",
    "encodings/cp932.pyc",
    "encodings/cp875.pyc",
    "encodings/cp874.pyc",
    "encodings/cp869.pyc",
    "encodings/cp866.pyc",
    "encodings/cp865.pyc",
    "encodings/cp864.pyc",
    "encodings/cp863.pyc",
    "encodings/cp862.pyc",
    "encodings/cp861.pyc",
    "encodings/cp860.pyc",
    "encodings/cp858.pyc",
    "encodings/cp857.pyc",
    "encodings/cp856.pyc",
    "encodings/cp855.pyc",
    "encodings/cp852.pyc",
    "encodings/cp850.pyc",
    "encodings/cp775.pyc",
    "encodings/cp737.pyc",
    "encodings/cp720.pyc",
    "encodings/cp500.pyc",
    "encodings/cp437.pyc",
    "encodings/cp424.pyc",
    "encodings/cp273.pyc",
    "encodings/cp1258.pyc",
    "encodings/cp1257.pyc",
    "encodings/cp1256.pyc",
    "encodings/cp1255.pyc",
    "encodings/cp1254.pyc",
    "encodings/cp1253.pyc",
    "encodings/cp1252.pyc",
    "encodings/cp1251.pyc",
    "encodings/cp1250.pyc",
    "encodings/cp1140.pyc",
    "encodings/cp1125.pyc",
    "encodings/cp1026.pyc",
    "encodings/cp1006.pyc",
    "encodings/cp037.pyc",
    "encodings/charmap.pyc",
    "encodings/bz2_codec.pyc",
    "encodings/big5hkscs.pyc",
    "encodings/big5.pyc",
    "encodings/base64_codec.pyc",
    "encodings/ascii.pyc",
    "encodings/aliases.pyc",
    "encodings/__init__.pyc",
    "linecache.pyc",
    "copyreg.pyc",
    "os.pyc",
)


def normalize_supervisor_exe(exe_path: Path) -> None:
    """Normalize PyInstaller onefile packing details for Supervisor."""
    exe_path = Path(exe_path)
    exe = exe_path.read_bytes()
    archive = CArchiveReader(str(exe_path))

    cookie_start = archive._end_offset - CArchiveReader._COOKIE_LENGTH
    magic, _archive_length, toc_offset, toc_length, pyvers, pylib_name = struct.unpack(
        CArchiveReader._COOKIE_FORMAT,
        exe[cookie_start:archive._end_offset],
    )
    raw_pkg = exe[archive._start_offset:archive._end_offset]
    raw_toc = raw_pkg[toc_offset:toc_offset + toc_length]
    entries = _parse_toc(raw_toc)

    normalized_zip = _normalize_base_library_zip(archive.extract("base_library.zip"))
    normalized_zip_compressed = zlib.compress(
        normalized_zip,
        level=CArchiveWriter._COMPRESSION_LEVEL,
    )

    payload = bytearray()
    rebuilt_toc = []
    for name, entry_offset, data_length, uncompressed_length, compression_flag, typecode in entries:
        if name == "base_library.zip":
            data = normalized_zip_compressed
            uncompressed_length = len(normalized_zip)
            compression_flag = 1
        else:
            data = raw_pkg[entry_offset:entry_offset + data_length]

        new_offset = len(payload)
        payload.extend(data)
        rebuilt_toc.append((
            new_offset,
            len(data),
            uncompressed_length,
            compression_flag,
            typecode,
            name,
        ))

    new_toc = CArchiveWriter._serialize_toc(rebuilt_toc)
    new_cookie = struct.pack(
        CArchiveReader._COOKIE_FORMAT,
        magic,
        len(payload) + len(new_toc) + CArchiveReader._COOKIE_LENGTH,
        len(payload),
        len(new_toc),
        pyvers,
        pylib_name,
    )
    tmp_path = exe_path.with_suffix(exe_path.suffix + ".tmp")
    tmp_path.write_bytes(exe[:archive._start_offset] + bytes(payload) + new_toc + new_cookie)
    winutils.set_exe_build_timestamp(str(tmp_path), SUPERVISOR_BUILD_TIMESTAMP)
    winutils.update_exe_pe_checksum(str(tmp_path))
    tmp_path.replace(exe_path)


def _parse_toc(toc_data: bytes) -> list[tuple[str, int, int, int, int, str]]:
    entries: list[tuple[str, int, int, int, int, str]] = []
    position = 0
    while position < len(toc_data):
        entry_length, entry_offset, data_length, uncompressed_length, compression_flag, typecode = struct.unpack(
            CArchiveReader._TOC_ENTRY_FORMAT,
            toc_data[position:position + CArchiveReader._TOC_ENTRY_LENGTH],
        )
        name_start = position + CArchiveReader._TOC_ENTRY_LENGTH
        name = toc_data[name_start:position + entry_length].rstrip(b"\0").decode("utf-8")
        entries.append((
            name,
            entry_offset,
            data_length,
            uncompressed_length,
            compression_flag,
            typecode.decode("ascii"),
        ))
        position += entry_length
    return entries


def _normalize_base_library_zip(zip_data: bytes) -> bytes:
    source = io.BytesIO(zip_data)
    target = io.BytesIO()
    with zipfile.ZipFile(source, "r") as source_zip:
        source_names = set(source_zip.namelist())
        order = [name for name in SUPERVISOR_BASE_LIBRARY_ORDER if name in source_names]
        order.extend(name for name in source_zip.namelist() if name not in set(order))

        with zipfile.ZipFile(target, "w") as target_zip:
            for name in order:
                source_info = source_zip.getinfo(name)
                target_info = zipfile.ZipInfo(name)
                target_info.date_time = source_info.date_time
                target_info.compress_type = source_info.compress_type
                target_info.comment = source_info.comment
                target_info.extra = source_info.extra
                target_info.internal_attr = source_info.internal_attr
                target_info.external_attr = source_info.external_attr
                target_info.create_system = source_info.create_system
                target_zip.writestr(target_info, source_zip.read(name))
    return target.getvalue()
