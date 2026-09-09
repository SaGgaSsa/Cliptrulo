"""Asegura chamu-cli.exe local actualizado desde GitHub.

Fuente default: prerelease (`--source release --release-tag chamu-cli-dev`):
compara el digest sha256 del asset con VERSION.json local y descarga el
exe solo si cambió. Alternativa: artefacto de Actions (`--source run`).
Imprime CHAMU_CLI=<ruta exe>.

Usage:
  python tools/ensure_chamu_cli.py [--dir tools/chamu-cli]
      [--repo SaGgaSsa/chamu] [--source release|run]
      [--release-tag chamu-cli-dev] [--asset chamu-cli.exe]
      [--workflow cli.yml] [--artifact chamu-cli-windows-x64] [--branch ""]

Exit 0: exe listo (una línea de estado + CHAMU_CLI=<ruta>).
Exit 1: uso inválido. Exit 2: sin exe disponible (p. ej. falta `gh auth login`
y no hay copia local).
"""
import datetime
import json
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULTS = {"dir": "tools/chamu-cli", "repo": "SaGgaSsa/chamu",
            "source": "release", "release-tag": "chamu-cli-dev",
            "asset": "chamu-cli.exe",
            "workflow": "cli.yml", "artifact": "chamu-cli-windows-x64",
            "branch": ""}
VERSION_FILE = "VERSION.json"
EXE_NAME = "chamu-cli.exe"
GH_FALLBACK = r"C:\Program Files\GitHub CLI\gh.exe"


def fail(msg):
    print(msg, file=sys.stderr)
    return 2


def find_gh():
    p = shutil.which("gh")
    if p:
        return p
    if Path(GH_FALLBACK).is_file():
        return GH_FALLBACK
    return None


def run_gh(gh, *args):
    try:
        r = subprocess.run([gh, *args], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return None, str(e)
    if r.returncode != 0:
        return None, (r.stderr or r.stdout).strip()[:300]
    return r.stdout.strip(), ""


def main():
    opts = dict(DEFAULTS)
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i].startswith("--") and args[i][2:] in opts and i + 1 < len(args):
            opts[args[i][2:]] = args[i + 1]
            i += 2
        else:
            sys.exit(f"flag inválido: {args[i]} (uso: {[k for k in opts]})")

    dest = Path(opts["dir"])
    dest.mkdir(parents=True, exist_ok=True)
    local_exe = dest / EXE_NAME
    local_ver = {}
    vf = dest / VERSION_FILE
    if vf.is_file():
        try:
            local_ver = json.loads(vf.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            local_ver = {}

    def emit(status):
        print(status)
        print(f"CHAMU_CLI={local_exe.resolve()}")
        return 0

    gh = find_gh()
    if gh is None:
        if local_exe.is_file():
            print("WARN: gh no instalado, se usa copia local (sin chequeo de versión)")
            return emit("LOCAL-FALLBACK")
        return fail("ERROR: gh no instalado y sin copia local "
                      "(winget install GitHub.cli)")

    if opts["source"] == "release":
        return ensure_release(gh, opts, dest, local_exe, local_ver, vf, emit)
    elif opts["source"] == "run":
        return ensure_run(gh, opts, dest, local_exe, local_ver, vf, emit)
    else:
        sys.exit(f"flag inválido: --source debe ser release|run")


def ensure_release(gh, opts, dest, local_exe, local_ver, vf, emit):
    out, err = run_gh(gh, "release", "view", opts["release-tag"],
                      "--repo", opts["repo"], "--json", "assets")
    if out is None:
        if local_exe.is_file():
            print(f"WARN: no se pudo consultar GitHub ({err}); se usa copia local")
            return emit("LOCAL-FALLBACK")
        return fail(f"ERROR: sin acceso a GitHub y sin copia local ({err}). "
                      "Corre `gh auth login`.")
    try:
        assets = json.loads(out).get("assets", [])
    except json.JSONDecodeError:
        assets = []
    asset = next((a for a in assets if a.get("name") == opts["asset"]), None)
    if asset is None:
        if local_exe.is_file():
            print(f"WARN: asset {opts['asset']} no está en {opts['release-tag']}; "
                  "se usa copia local")
            return emit("LOCAL-FALLBACK")
        return fail(f"ERROR: asset {opts['asset']} no está en "
                    f"{opts['release-tag']} ni hay copia local.")
    digest = asset.get("digest", "")
    if local_ver.get("digest") == digest and digest and local_exe.is_file():
        print(f"OK: chamu-cli al día ({opts['release-tag']} {digest[:19]}...)")
        return emit("UP-TO-DATE")
    print(f"nuevo digest {digest[:19]}... (local: "
          f"{str(local_ver.get('digest'))[:19]}); descargando...")
    out, err = run_gh(gh, "release", "download", opts["release-tag"],
                      "-p", opts["asset"], "-D", str(dest),
                      "--repo", opts["repo"], "--clobber")
    if out is None:
        if local_exe.is_file():
            print(f"WARN: descarga falló ({err}); se usa copia local")
            return emit("LOCAL-FALLBACK")
        return fail(f"ERROR: descarga falló y sin copia local ({err}).")
    found = next(dest.rglob(EXE_NAME), None)
    if found is None or not found.is_file():
        return fail(f"ERROR: release descargado sin {EXE_NAME}.")
    if found != local_exe:
        local_exe.unlink(missing_ok=True)
        found.rename(local_exe)
    vf.write_text(json.dumps({
        "source": "release", "repo": opts["repo"],
        "release_tag": opts["release-tag"], "asset": opts["asset"],
        "digest": digest,
        "downloaded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }, indent=2), encoding="utf-8")
    print(f"OK: chamu-cli actualizado ({opts['release-tag']} {digest[:19]}...)")
    return emit("DOWNLOADED")


def ensure_run(gh, opts, dest, local_exe, local_ver, vf, emit):
    list_cmd = ["run", "list", "--repo", opts["repo"],
                "--workflow", opts["workflow"], "--status", "success",
                "--limit", "1", "--json", "databaseId,headSha,createdAt"]
    if opts["branch"]:
        list_cmd += ["--branch", opts["branch"]]
    out, err = run_gh(gh, *list_cmd)
    if out is None:
        if local_exe.is_file():
            print(f"WARN: no se pudo consultar GitHub ({err}); se usa copia local")
            return emit("LOCAL-FALLBACK")
        return fail(f"ERROR: sin acceso a GitHub y sin copia local ({err}). "
                      "Corre `gh auth login`.")
    try:
        latest = (json.loads(out) or [None])[0]
    except json.JSONDecodeError:
        latest = None
    if not latest:
        if local_exe.is_file():
            print("WARN: sin runs exitosos remotos; se usa copia local")
            return emit("LOCAL-FALLBACK")
        return fail("ERROR: sin runs exitosos remotos ni copia local.")

    run_id = str(latest["databaseId"])
    if local_ver.get("run_id") == run_id and local_exe.is_file():
        print(f"OK: chamu-cli al día (run {run_id})")
        return emit("UP-TO-DATE")

    print(f"nuevo run {run_id} (local: {local_ver.get('run_id')}); descargando...")
    out, err = run_gh(gh, "run", "download", run_id, "-n", opts["artifact"],
                      "-D", str(dest), "--repo", opts["repo"])
    if out is None:
        if local_exe.is_file():
            print(f"WARN: descarga falló ({err}); se usa copia local "
                  "(el artefacto expira a los 14 días)")
            return emit("LOCAL-FALLBACK")
        return fail(f"ERROR: descarga falló y sin copia local ({err}).")
    found = next(dest.rglob(EXE_NAME), None)
    if found is None or not found.is_file():
        return fail(f"ERROR: artefacto descargado sin {EXE_NAME}.")
    if found != local_exe:
        local_exe.unlink(missing_ok=True)
        found.rename(local_exe)
    vf.write_text(json.dumps({
        "repo": opts["repo"], "workflow": opts["workflow"],
        "artifact": opts["artifact"], "run_id": run_id,
        "head_sha": latest.get("headSha"), "run_created_at": latest.get("createdAt"),
        "downloaded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }, indent=2), encoding="utf-8")
    print(f"OK: chamu-cli actualizado a run {run_id}")
    return emit("DOWNLOADED")


if __name__ == "__main__":
    sys.exit(main())
