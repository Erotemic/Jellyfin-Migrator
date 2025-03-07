from string import ascii_letters
import datetime
import hashlib
import pathlib
from pathlib import Path


def get_dotnet_MD5(s: str):
    """
    Note: The .NET .Unicode method encodes as UTF16 little endian:
    https://docs.microsoft.com/en-us/dotnet/api/system.text.encoding.unicode?view=net-6.0
    """
    return hashlib.md5(s.encode("utf-16-le")).digest()


def nested_id_path_replacer(d, to_replace: dict):
    """
    Almost the same as nested_root_path_replacer but for replacing id parts somewhere in
    the paths including file names (can't use "is_relative_to" for checking).
    ID paths usually have the format '.../83/833addde992893e93d0572907f8b4cad/...'. It's
    important to note and change that parent folder with the firs byte of the id, too.
    Sometimes the parent folder is just single digit. This code handles any subsring that
    starts at the beginning of the id string.
    """
    modified, ignored = 0, 0
    if isinstance(d, dict):
        for k, v in d.items():
            d[k], mo, ig = nested_id_path_replacer(v, to_replace)
            modified += mo
            ignored  += ig
    elif isinstance(d, list):
        for i, e in enumerate(d):
            d[i], mo, ig = nested_id_path_replacer(e, to_replace)
            modified += mo
            ignored  += ig
    elif isinstance(d, str) or isinstance(d, pathlib.PurePath):
        try:
            p = Path(d)
        except Exception:
            # This actually doesn't occur I think; Path() can pretty much convert any string into a Path
            # object (which is equivalent to saying it doesn't have any restrictions for filenames).
            ignored += 1
        else:
            found = False

            src, dst = "", ""

            if set(p.stem).issubset(set("0123456789abcdef-")):
                dst = to_replace.get(p.stem, "")
                if dst:
                    found = True
                    p = p.with_stem(dst)

            if not found:
                for part in p.parts[:-1]:
                    # Check if it can actually be an ID. If so, look it up (which is expensive).
                    if set(part).issubset(set("0123456789abcdef-")):
                        src = part
                        dst = to_replace.get(part, "")
                        if dst:
                            break
                if dst:
                    found = True
                    q = Path()
                    # Find folder as path object that needs to be changed
                    q = p
                    while p.name != src:
                        p = p.parent
                    # q becomes the part relative to the now determined p part (with p.stem = id)
                    q = q.relative_to(p)
                    p = p.with_name(dst)

                    # Check if the parent folder starts with byte(s) from the id
                    if src.startswith(p.parent.name):
                        # If so, move the already replaced part from p to q
                        q = p.name / q
                        p = p.parent
                        # Replace required number of bytes
                        p = p.with_name(dst[:len(p.name)])

                    # Merge q and p back together
                    p = p / q
            if found:
                modified += 1
                # I guess 99% of the users won't migrate _to_ windows but the script could generate
                # \ paths anyways.
                # p.as_posix() makes sure that we always get a string with "/". Otherwise, on windows,
                # str(p) would automatically return "\" paths.
                d = p.as_posix().replace("/", to_replace["target_path_slash"])
            else:
                ignored += 1
                # Unlike nested_root_path_replacer, there is no need to warn the user about
                # potential paths that haven't been altered. In case you suspect that something is
                # overlooked, check out ./id_scanner.py.
                # ignored is purely maintained for signature compatibility with nested_root_path_replacer.
    return d, modified, ignored


def jf_date_str_to_python_ns(s: str):
    # Python datetime has only support for microseconds because of resolution
    # problems. To convert from a date+time to ticks, the fractional seconds
    # part doesn't matter anyway (it remains the same). Hence, it's cut off
    # and added back later.
    subseconds = "0"
    if "." in s:
        s, subseconds = s.rsplit(".", 1)
    # In case subseconds has a higher resolution than 100ns and/or additional
    # information (f.ex. timezone, which is known to be UTC+00:00 for jellyfin),
    # Strip all of it.
    # Add trailing zeros til the ns digit, then convert to int, and we have ns.
    subseconds = int(subseconds.split("+")[0].rstrip(ascii_letters).ljust(9, "0"))
    # Add explicit information about the timezone (UTC+00:00)
    s += "+00:00"
    t = int(datetime.datetime.fromisoformat(s).timestamp())
    # Convert to ns
    t *= 1000000000
    t += subseconds
    return t


def get_datestr_from_python_time_ns(time_ns: int):
    """
    Convert a _python_ timestamp (float seconds since epoch, which is os dependent)
    to a ISO like date string as found in the jellyfin database. I have no idea
    if this works for all OS'es in all timezones. Very likely not but that whole
    topic is about as much of a mess as jellyfin's databases. If you got any issues,
    I'm sorry. If you find a solution, them, please let me know!
    """
    # Datetime has no support for sub-microsecond resolution (which is required here).
    # Doesn't matter anyway, we can add the whole sub-second part afterwards.
    time_s = time_ns // 1000000000
    time_frac_s_100ns = (time_ns // 100) % 10000000
    timestamp = datetime.datetime.utcfromtimestamp(time_s).isoformat(sep=" ", timespec="seconds")
    # Add back the sub-seconds part and the UTC time zone
    timestamp += "." + str(time_frac_s_100ns).rjust(7, "0").rstrip("0") + "Z"
    return timestamp


def delete_empty_folders(dir: str):
    dir = Path(dir)

    done = False
    while not done:
        done = True
        for p in dir.glob("**"):
            if not list(p.iterdir()):
                p.rmdir()
                done = False


