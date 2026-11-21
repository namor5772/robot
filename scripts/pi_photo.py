"""See a photo from the Pi on a PC.

Run on a PC, from the checkout:

    .venv/Scripts/python.exe scripts/pi_photo.py              the newest photo
    .venv/Scripts/python.exe scripts/pi_photo.py NAME.jpg     that photo
    .venv/Scripts/python.exe scripts/pi_photo.py --file F.jpg a file already here

It copies the photo from the Pi's ~/robot-photos into ~/RobotPhotos on the PC
and opens it in the PC's own viewer. Nothing on the Pi is changed.

Why it is more than a copy: the robot's photos are frames of the webcam's
MJPG stream, and such a frame is a JPEG file without its Huffman tables. The
stream's convention is that the standard tables of the JPEG standard (ITU
T.81, Annex K.3) are meant. Lenient decoders fill them in, and the model sees
these photos without trouble. Windows' own decoder refuses the file: the
viewer opens and shows nothing. So the copy that is opened, NAME_viewable.jpg,
has those tables put in front of the picture data. The picture data is not
touched, and the photo as it came is kept beside it.

Photos are personal. The folder they go to must not be inside the checkout
(the repo is public) or inside a folder that OneDrive copies elsewhere.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PHOTOS_ON_PI = "robot-photos"  # in the home folder of the Pi's user
SSH_OPTIONS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
ONEDRIVE_VARIABLES = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")

DC_LUMA_BITS = bytes.fromhex("00010501010101010100000000000000")
DC_CHROMA_BITS = bytes.fromhex("00030101010101010101010000000000")
DC_VALUES = bytes(range(12))

AC_LUMA_BITS = bytes.fromhex("0002010303020403050504040000017d")
AC_LUMA_VALUES = bytes.fromhex(
    "01020300041105122131410613516107"
    "227114328191a1082342b1c11552d1f0"
    "2433627282090a161718191a25262728"
    "292a3435363738393a43444546474849"
    "4a535455565758595a63646566676869"
    "6a737475767778797a83848586878889"
    "8a92939495969798999aa2a3a4a5a6a7"
    "a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5"
    "c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2"
    "e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8"
    "f9fa"
)
AC_CHROMA_BITS = bytes.fromhex("00020102040403040705040400010277")
AC_CHROMA_VALUES = bytes.fromhex(
    "00010203110405213106124151076171"
    "1322328108144291a1b1c109233352f0"
    "156272d10a162434e125f11718191a26"
    "2728292a35363738393a434445464748"
    "494a535455565758595a636465666768"
    "696a737475767778797a828384858687"
    "88898a92939495969798999aa2a3a4a5"
    "a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3"
    "c4c5c6c7c8c9cad2d3d4d5d6d7d8d9da"
    "e2e3e4e5e6e7e8e9eaf2f3f4f5f6f7f8"
    "f9fa"
)

# (table class and number, how many codes of each length, the values)
TABLES = [
    (0x00, DC_LUMA_BITS, DC_VALUES),
    (0x10, AC_LUMA_BITS, AC_LUMA_VALUES),
    (0x01, DC_CHROMA_BITS, DC_VALUES),
    (0x11, AC_CHROMA_BITS, AC_CHROMA_VALUES),
]

START_OF_IMAGE = b"\xff\xd8"
HUFFMAN_TABLES = 0xC4
START_OF_SCAN = 0xDA


def check_tables():
    """Raise if a table above was mistyped, before it can spoil a picture."""
    # An AC table codes every pair (run 0-15, size 1-10), plus 00 and F0.
    every_ac_value = {0x00, 0xF0} | {
        run << 4 | size for run in range(16) for size in range(1, 11)
    }
    for number, bits, values in TABLES:
        problem = "Huffman table %#04x is wrong" % number
        if len(bits) != 16 or sum(bits) != len(values):
            raise ValueError(problem)
        if len(set(values)) != len(values):
            raise ValueError(problem)
        if number & 0x10 and set(values) != every_ac_value:
            raise ValueError(problem)
        # No code length may be given more codes than there is room for.
        room = 1
        for count in bits:
            room = room * 2 - count
            if room < 0:
                raise ValueError(problem)


def huffman_segment():
    """The four standard tables as one JPEG segment."""
    body = b"".join(bytes([number]) + bits + values for number, bits, values in TABLES)
    return b"\xff" + bytes([HUFFMAN_TABLES]) + (len(body) + 2).to_bytes(2, "big") + body


def segments(data):
    """The (marker, offset) of each segment, up to where the picture data starts."""
    if data[:2] != START_OF_IMAGE:
        raise ValueError("not a JPEG file")
    found = []
    at = 2
    while at + 4 <= len(data):
        if data[at] != 0xFF:
            raise ValueError("not a JPEG file: lost at byte %d" % at)
        marker = data[at + 1]
        found.append((marker, at))
        if marker == START_OF_SCAN:
            return found
        at += 2 + int.from_bytes(data[at + 2:at + 4], "big")
    raise ValueError("not a whole JPEG file: no picture data in it")


def with_huffman_tables(data):
    """The file with the standard tables put in, or `data` itself if it has tables."""
    check_tables()
    found = segments(data)
    if any(marker == HUFFMAN_TABLES for marker, _ in found):
        return data
    scan_at = found[-1][1]
    return data[:scan_at] + huffman_segment() + data[scan_at:]


def viewable_copy(photo):
    """Write NAME_viewable.jpg beside `photo` if it needs one. Returns what to open."""
    data = photo.read_bytes()
    fixed = with_huffman_tables(data)
    if fixed is data:
        return photo
    target = photo.with_name(photo.stem + "_viewable" + photo.suffix)
    target.write_bytes(fixed)
    return target


def safe_folder(folder, environ=None, repo=REPO):
    """The folder as a full path. Raises if photos must not be put there."""
    environ = os.environ if environ is None else environ
    folder = Path(folder).expanduser().resolve()
    forbidden = [(Path(repo).resolve(), "the checkout, and the repo is public")]
    for name in ONEDRIVE_VARIABLES:
        if environ.get(name):
            forbidden.append((Path(environ[name]).resolve(), "a folder that OneDrive copies"))
    for place, why in forbidden:
        if folder == place or place in folder.parents:
            raise ValueError("%s is inside %s" % (folder, why))
    return folder


def run_program(arguments):
    """Run ssh or scp. Returns (exit code, what it printed)."""
    done = subprocess.run(arguments, capture_output=True, text=True)
    return done.returncode, (done.stdout + done.stderr).strip()


def newest_on_pi(host, run=run_program):
    """The path, on the Pi, of the newest photo there."""
    command = "ls -t %s/*.jpg 2>/dev/null | head -n 1" % PHOTOS_ON_PI
    code, said = run(["ssh", *SSH_OPTIONS, host, command])
    if code != 0:
        raise RuntimeError("could not ask the Pi: %s" % (said or "ssh failed"))
    if not said:
        raise RuntimeError("the Pi has no photo in ~/%s" % PHOTOS_ON_PI)
    return said.splitlines()[-1].strip()


def copy_from_pi(host, remote, folder, run=run_program):
    """Copy one photo into `folder`. Returns the copy's path."""
    folder.mkdir(parents=True, exist_ok=True)
    code, said = run(["scp", *SSH_OPTIONS, "%s:%s" % (host, remote), str(folder)])
    if code != 0:
        raise RuntimeError("could not copy %s: %s" % (remote, said or "scp failed"))
    return folder / remote.rsplit("/", 1)[-1]


def show(path):
    """Open the file in the PC's own viewer, where there is one to ask for."""
    if hasattr(os, "startfile"):
        os.startfile(str(path))
        return True
    return False


def fetch_and_show(name=None, local=None, folder="~/RobotPhotos", host="pi",
                   open_it=True, run=run_program, show=show, say=print,
                   environ=None):
    """The whole job. Returns the path of the file that can be viewed."""
    if local:
        photo = Path(local).expanduser()
        if not photo.is_file():
            raise RuntimeError("no such file: %s" % photo)
    else:
        folder = safe_folder(folder, environ)
        if name:
            if "/" in name or "\\" in name:
                raise RuntimeError("give the photo's file name only, not a path")
            remote = "%s/%s" % (PHOTOS_ON_PI, name)
        else:
            remote = newest_on_pi(host, run)
            say("newest on the Pi: %s" % remote.rsplit("/", 1)[-1])
        photo = copy_from_pi(host, remote, folder, run)
        say("copied to: %s" % photo)
    result = viewable_copy(photo)
    if result != photo:
        say("it had no Huffman tables; viewable copy: %s" % result)
    if open_it:
        say("opened in the viewer" if show(result) else "open it by hand: %s" % result)
    return result


def build_parser():
    parser = argparse.ArgumentParser(
        description="Copy a photo from the Pi to this PC and open it in a viewer.")
    parser.add_argument("name", nargs="?",
                        help="a photo's file name on the Pi (default: the newest)")
    parser.add_argument("--file", dest="local",
                        help="a photo already on this PC: only make it viewable")
    parser.add_argument("--dir", dest="folder", default="~/RobotPhotos",
                        help="where copies go on this PC (default: %(default)s)")
    parser.add_argument("--host", default="pi", help="the ssh name of the Pi")
    parser.add_argument("--no-open", dest="open_it", action="store_false",
                        help="do not open the viewer")
    return parser


def main(arguments=None):
    options = build_parser().parse_args(arguments)
    try:
        fetch_and_show(options.name, options.local, options.folder, options.host,
                       options.open_it)
    except (RuntimeError, ValueError, OSError) as problem:
        print("error: %s" % problem, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
