import argparse
import hashlib
import io
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

MAVEN_BASE = "https://repo1.maven.org/maven2/org/eclipse/jdt/ecj"
JAVAX_JAR_URL = "https://repo1.maven.org/maven2/com/zeoflow/jx/1.2.1/jx-1.2.1.jar"
R8_JAR_URL = "https://dl.google.com/android/maven2/com/android/tools/r8/8.2.42/r8-8.2.42.jar"
TESTKEY_BASE = "https://raw.githubusercontent.com/android/platform_build/master/target/product/security/testkey"


def find_android_sdk() -> Path | None:
    env_paths = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")]
    for env in env_paths:
        if env and Path(env).exists():
            return Path(env)

    common_roots = [
        Path("G:/Android-SDK"),
        Path.home() / "AppData" / "Local" / "Android" / "Sdk",
        Path.home() / "Android" / "Sdk",
        Path("/opt/android-sdk"),
        Path("/usr/lib/android-sdk"),
    ]
    for root in common_roots:
        if root.exists():
            return root
    return None


def get_build_tools_pair(sdk: Path) -> tuple[Path, str] | None:
    bt_dir = sdk / "build-tools"
    if not bt_dir.exists():
        return None

    preferred = ["34.0.0", "35.0.0", "33.0.2", "30.0.3"]
    bts = [bt_dir / v for v in preferred if (bt_dir / v).is_dir()] + sorted(
        [p for p in bt_dir.iterdir() if p.is_dir()], reverse=True
    )

    for bt in bts:
        for cand in [bt / "d8.bat", bt / "d8"]:
            if cand.exists() and (bt / "lib" / "d8.jar").exists():
                return bt, str(cand)
    return None


def get_sdk_platform(sdk: Path) -> Path | None:
    platforms_dir = sdk / "platforms"
    if not platforms_dir.exists():
        return None

    preferred = ["android-34", "android-35", "android-33"]
    plats = [platforms_dir / v for v in preferred if (platforms_dir / v).is_dir()] + sorted(
        [p for p in platforms_dir.iterdir() if p.is_dir()], reverse=True
    )

    for p in plats:
        if (p / "android.jar").exists():
            return p
    return None


def build_android(target_dir: Path, sdk: Path | None = None) -> bool:
    sdk = sdk or find_android_sdk()
    if not sdk:
        print("[-] Android SDK not found (set ANDROID_HOME)")
        return False

    platform = get_sdk_platform(sdk)
    if not platform:
        print("[-] Android SDK platform android.jar not found")
        return False

    target_dir.mkdir(parents=True, exist_ok=True)
    src_jar = platform / "android.jar"
    dest_jar = target_dir / "android.jar"
    dest_classes = target_dir / "android.classes.jar"

    print(f"[*] copying android.jar from {platform.name}")
    shutil.copyfile(src_jar, dest_jar)

    print("[*] creating android.classes.jar")
    with zipfile.ZipFile(src_jar, "r") as zin:
        with zipfile.ZipFile(dest_classes, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename.endswith(".class"):
                    zout.writestr(item, zin.read(item.filename))

    return True


def build_d8(target_dir: Path, sdk: Path | None = None) -> bool:
    sdk = sdk or find_android_sdk()
    if not sdk:
        print("[-] Android SDK not found")
        return False

    bt_pair = get_build_tools_pair(sdk)
    platform = get_sdk_platform(sdk)

    if not bt_pair or not platform:
        print("[-] build-tools or platform missing for d8 dexing")
        return False

    bt, d8_cmd = bt_pair
    d8_jar = bt / "lib" / "d8.jar"
    android_jar = platform / "android.jar"
    target_dir.mkdir(parents=True, exist_ok=True)
    output_dex = target_dir / "d8.dex"

    print(f"[*] compiling d8.dex from {bt.name}")
    with tempfile.TemporaryDirectory() as tmp:
        tpath = Path(tmp)
        out_jar = tpath / "d8_out.jar"
        subprocess.run([d8_cmd, "--lib", str(android_jar), "--output", str(out_jar), str(d8_jar)], check=True)
        shutil.copyfile(out_jar, output_dex)

    return True


def build_apksigner(target_dir: Path, sdk: Path | None = None) -> bool:
    sdk = sdk or find_android_sdk()
    if not sdk:
        print("[-] Android SDK not found")
        return False

    bt_pair = get_build_tools_pair(sdk)
    platform = get_sdk_platform(sdk)

    if not bt_pair or not platform:
        print("[-] build-tools or platform missing for apksigner dexing")
        return False

    bt, d8_cmd = bt_pair
    apksigner_jar = bt / "lib" / "apksigner.jar"
    android_jar = platform / "android.jar"
    target_dir.mkdir(parents=True, exist_ok=True)
    output_dex = target_dir / "apksigner.dex"

    print(f"[*] compiling apksigner.dex from {bt.name}")
    with tempfile.TemporaryDirectory() as tmp:
        tpath = Path(tmp)
        subprocess.run([d8_cmd, "--lib", str(android_jar), "--output", str(tpath), str(apksigner_jar)], check=True)
        shutil.copyfile(tpath / "classes.dex", output_dex)

    return True


def patch_sources(src_dir: Path) -> None:
    util_file = src_dir / "org" / "eclipse" / "jdt" / "internal" / "compiler" / "util" / "Util.java"
    if util_file.exists():
        text = util_file.read_text(encoding="utf-8")

        new_get_bytes = """public static byte[] getInputStreamAsByteArray(InputStream input) throws IOException {
\t\tjava.io.ByteArrayOutputStream buffer = new java.io.ByteArrayOutputStream();
\t\tbyte[] data = new byte[8192];
\t\tint nRead;
\t\twhile ((nRead = input.read(data, 0, data.length)) != -1) {
\t\t\tbuffer.write(data, 0, nRead);
\t\t}
\t\treturn buffer.toByteArray();
\t}"""

        new_read_n = """public static byte[] readNBytes(InputStream input, int byteLength) throws IOException {
\t\tjava.io.ByteArrayOutputStream buffer = new java.io.ByteArrayOutputStream();
\t\tbyte[] data = new byte[Math.min(byteLength, 8192)];
\t\tint totalRead = 0;
\t\twhile (totalRead < byteLength) {
\t\t\tint toRead = Math.min(data.length, byteLength - totalRead);
\t\t\tint nRead = input.read(data, 0, toRead);
\t\t\tif (nRead == -1) break;
\t\t\tbuffer.write(data, 0, nRead);
\t\t\ttotalRead += nRead;
\t\t}
\t\treturn buffer.toByteArray();
\t}"""

        text = re.sub(
            r"public static byte\[\] getInputStreamAsByteArray\(InputStream input\) throws IOException \{.*?\n\t\}",
            new_get_bytes,
            text,
            flags=re.DOTALL,
        )
        text = re.sub(
            r"public static byte\[\] readNBytes\(InputStream input, int byteLength\) throws IOException \{.*?\n\t\}",
            new_read_n,
            text,
            flags=re.DOTALL,
        )
        util_file.write_text(text, encoding="utf-8")

    subword_file = src_dir / "org" / "eclipse" / "jdt" / "core" / "compiler" / "SubwordMatcher.java"
    if subword_file.exists():
        stext = subword_file.read_text(encoding="utf-8")
        new_case = """private static final int CASE_SEPARATOR = 0;
\tprivate static final int CASE_LOWER = 1;
\tprivate static final int CASE_UPPER = 2;

\tprivate int caseAt(int index) {
\t\tif (index < 0 || index >= this.name.length)
\t\t\treturn CASE_SEPARATOR;

\t\tchar c = this.name[index];
\t\tif (c == '_')
\t\t\treturn CASE_SEPARATOR;
\t\tif (ScannerHelper.isUpperCase(c))
\t\t\treturn CASE_UPPER;
\t\treturn CASE_LOWER;
\t}

\tprivate static boolean isWordBoundary(int p, int c, int n) {
\t\tif (p == c && c == n)
\t\t\treturn false;

\t\tif (p == CASE_SEPARATOR)
\t\t\treturn true;

\t\treturn (c == CASE_UPPER) && (p == CASE_LOWER || n == CASE_LOWER);
\t}"""

        stext = re.sub(
            r"(?:private\s+)?Case\s+caseAt\(int\s+index\)\s*\{.*?enum\s+Case\s*\{[^}]*\}",
            new_case,
            stext,
            flags=re.DOTALL,
        )
        subword_file.write_text(stext, encoding="utf-8")


def build_ecj(target_dir: Path, version: str = "3.27.0") -> bool:
    target_dir.mkdir(parents=True, exist_ok=True)
    output_jar = target_dir / "ecj.jar"
    sdk = find_android_sdk()
    bt_pair = get_build_tools_pair(sdk) if sdk else None
    d8_cmd = bt_pair[1] if bt_pair else None

    with tempfile.TemporaryDirectory() as tmp:
        src_dir = Path(tmp) / "src"
        src_dir.mkdir()

        print(f"[*] fetching ecj {version} sources")
        with urllib.request.urlopen(f"{MAVEN_BASE}/{version}/ecj-{version}-sources.jar") as resp:
            with zipfile.ZipFile(io.BytesIO(resp.read())) as z:
                z.extractall(src_dir)

        print("[*] patching sources for Dalvik compatibility")
        patch_sources(src_dir)

        bootstrap_jar = Path(tmp) / f"ecj-{version}-bootstrap.jar"
        with urllib.request.urlopen(f"{MAVEN_BASE}/{version}/ecj-{version}.jar") as resp:
            bootstrap_jar.write_bytes(resp.read())

        bin_dir = src_dir / "bin"
        bin_dir.mkdir()
        java_files = [f.as_posix() for f in (src_dir / "org").rglob("*.java") if f.name != "JDTCompilerAdapter.java"]
        sources_file = src_dir / "sources.txt"
        sources_file.write_text("\n".join(java_files), encoding="utf-8")

        print("[*] compiling java sources (requires OpenJDK)")
        subprocess.run(["java", "-jar", str(bootstrap_jar), "-11", "-d", str(bin_dir), f"@{sources_file}"], check=True)

        print("[*] packaging ecj.jar")
        resource_files = set()
        for pattern in ["**/*.rsc", "**/*.properties", "**/readableNames.props", "about.html", "ecj.1"]:
            for res_file in src_dir.glob(pattern):
                if "bin" not in res_file.parts:
                    resource_files.add(res_file)

        with zipfile.ZipFile(output_jar, "w", zipfile.ZIP_DEFLATED) as z:
            for f in bin_dir.rglob("*.class"):
                z.write(f, f.relative_to(bin_dir).as_posix())
            for res_file in sorted(resource_files):
                z.write(res_file, res_file.relative_to(src_dir).as_posix())
            manifest = "Manifest-Version: 1.0\nMain-Class: org.eclipse.jdt.internal.compiler.batch.Main\n\n"
            z.writestr("META-INF/MANIFEST.MF", manifest)

        print("[*] fetching JSR-269 javax packages")
        with urllib.request.urlopen(JAVAX_JAR_URL) as resp:
            with zipfile.ZipFile(io.BytesIO(resp.read())) as z_jx:
                javax_items = [i for i in z_jx.infolist() if i.filename.startswith("javax/")]
                with zipfile.ZipFile(output_jar, "a") as zout:
                    existing = set(zout.namelist())
                    for item in javax_items:
                        if item.filename not in existing:
                            zout.writestr(item.filename, z_jx.read(item.filename))

        print("[*] generating classes.dex with d8")
        dex_file = Path(tmp) / "classes.dex"
        if d8_cmd:
            subprocess.run([d8_cmd, "--output", tmp, str(output_jar)], check=True)
        else:
            r8_jar = Path(tmp) / "r8.jar"
            with urllib.request.urlopen(R8_JAR_URL) as resp:
                r8_jar.write_bytes(resp.read())
            subprocess.run(["java", "-cp", str(r8_jar), "com.android.tools.r8.D8", "--output", tmp, str(output_jar)], check=True)

        with zipfile.ZipFile(output_jar, "a") as z:
            z.write(dex_file, "classes.dex")

    return True


def build_keys(target_dir: Path) -> bool:
    target_dir.mkdir(parents=True, exist_ok=True)
    pk8_file = target_dir / "debug.pk8"
    pem_file = target_dir / "debug.x509.pem"

    if pk8_file.exists() and pem_file.exists():
        return True

    print("[*] fetching default Android debug keys")
    try:
        with urllib.request.urlopen(f"{TESTKEY_BASE}.pk8") as resp:
            pk8_file.write_bytes(resp.read())
        with urllib.request.urlopen(f"{TESTKEY_BASE}.x509.pem") as resp:
            pem_file.write_bytes(resp.read())
        return True
    except Exception as e:
        print(f"[-] failed to fetch debug keys: {e}")
        return False


def build_all(target_dir: Path) -> bool:
    sdk = find_android_sdk()
    if sdk:
        print(f"[*] detected Android SDK: {sdk}")
    else:
        print("[!] Android SDK not found, please set ANDROID_HOME")

    success = True
    success = build_android(target_dir, sdk) and success
    success = build_d8(target_dir, sdk) and success
    success = build_apksigner(target_dir, sdk) and success
    success = build_ecj(target_dir) and success
    success = build_keys(target_dir) and success
    return success


def create_toolchain_archive(target_dir: Path, archive_path: Path) -> None:
    print(f"[*] packaging {archive_path.name}")
    files = [
        "android.jar",
        "android.classes.jar",
        "ecj.jar",
        "d8.dex",
        "apksigner.dex",
        "debug.pk8",
        "debug.x509.pem",
    ]
    with tarfile.open(archive_path, "w:gz") as tar:
        for fname in files:
            fpath = target_dir / fname
            if fpath.exists():
                tar.add(fpath, arcname=fname)


def generate_checksums(target_dir: Path) -> None:
    checksums_file = target_dir / "checksums.sha256"
    lines = []
    for fpath in sorted(target_dir.glob("*")):
        if fpath.is_file() and fpath.name != "checksums.sha256":
            digest = hashlib.sha256(fpath.read_bytes()).hexdigest()
            lines.append(f"{digest}  {fpath.name}")
    checksums_file.write_text("\n".join(lines) + "\n")
    print(f"[*] generated {checksums_file.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Kosei toolchain dependencies from source and SDK")
    parser.add_argument(
        "target",
        nargs="?",
        default="all",
        choices=["all", "ecj", "d8", "apksigner", "android", "keys"],
        help="Target component to build (default: all)",
    )
    parser.add_argument("-o", "--output", type=Path, default=Path("./dist"), help="Output directory (default: ./dist)")
    parser.add_argument("--archive", action="store_true", help="Create toolchain.tar.gz bundle")
    args = parser.parse_args()

    out_dir = args.output.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    targets = {
        "all": lambda: build_all(out_dir),
        "ecj": lambda: build_ecj(out_dir),
        "d8": lambda: build_d8(out_dir),
        "apksigner": lambda: build_apksigner(out_dir),
        "android": lambda: build_android(out_dir),
        "keys": lambda: build_keys(out_dir),
    }

    action = targets.get(args.target)
    if action and action():
        if args.archive or args.target == "all":
            create_toolchain_archive(out_dir, out_dir / "toolchain.tar.gz")
            generate_checksums(out_dir)
        print(f"[+] build complete: {out_dir}")


if __name__ == "__main__":
    main()
