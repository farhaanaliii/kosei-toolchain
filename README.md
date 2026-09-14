<div align="center">

# kosei-toolchain

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)](#)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Android%20%7C%20Linux%20%7C%20Windows-blue.svg)](#)

Toolchain builder and release assets for the Kosei Android on-device build pipeline.

</div>

## Overview

This repository builds, patches, and publishes the runtime binary toolchain required by Kosei to compile, package, and sign Android APKs on Termux.

Artifacts published in GitHub Releases include both a consolidated bundle (`toolchain.tar.gz`) and standalone component binaries:
- `android.jar`: Android SDK API stubs for resource linking via aapt2.
- `android.classes.jar`: Runtime framework definitions for Java compilation.
- `ecj.jar`: Eclipse Compiler for Java 3.27.0, patched for Dalvik bytecode execution and bundled with JSR-269 javax stubs.
- `d8.dex`: Android D8 dexer packaged as Dalvik-executable DEX.
- `apksigner.dex`: Android APK signing utility packaged as Dalvik-executable DEX.
- `debug.pk8` & `debug.x509.pem`: Standard Android debug keys for v1/v2/v3 APK signing.

## Prerequisites

Building the toolchain from source requires a desktop development environment:
- OpenJDK 11 or OpenJDK 17 (`java`, `javac`, `jar` must be available in PATH).
- Android SDK with build-tools (version 30.0.3 or newer containing `d8`) and at least one platform installed (e.g. `platforms/android-34`).
- Environment variable `ANDROID_HOME` or `ANDROID_SDK_ROOT` set to your Android SDK installation directory.
- Python >= 3.8.

## Usage

Build all toolchain artifacts and create `toolchain.tar.gz` bundle:

```bash
python build.py all -o ./dist
```

Build a specific component:

```bash
python build.py ecj -o ./dist
python build.py d8 -o ./dist
python build.py apksigner -o ./dist
python build.py android -o ./dist
python build.py keys -o ./dist
```

All built artifacts and their SHA-256 checksums will be generated in the specified output directory.

## Maintainer

Created and maintained by [Farhan Ali](https://github.com/farhaanaliii) (i.farhanali.dev@gmail.com).
