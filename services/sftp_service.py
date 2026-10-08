import io
import math
import os
import stat
import time
import urllib.request
import paramiko
from PyQt6.QtCore import QThread, pyqtSignal


def _list_recursive(sftp, remote_path: str, depth: int = 0) -> list:
    """Retourne l'arborescence sous remote_path comme liste de dicts."""
    if depth > 6:
        return []
    entries = []
    try:
        attrs = sftp.listdir_attr(remote_path)
    except Exception:
        return []
    for attr in attrs:
        is_dir = stat.S_ISDIR(attr.st_mode or 0)
        entry = {
            'name': attr.filename,
            'path': remote_path.rstrip('/') + '/' + attr.filename,
            'is_dir': is_dir,
            'size': attr.st_size or 0,
            'children': [],
        }
        if is_dir:
            entry['children'] = _list_recursive(sftp, entry['path'], depth + 1)
        entries.append(entry)
    entries.sort(key=lambda e: (not e['is_dir'], e['name'].lower()))
    return entries


class SftpConnectWorker(QThread):
    """Connexion SSH/SFTP et listing récursif du dossier distant (thread séparé)."""

    connected = pyqtSignal(list)   # arborescence d'entrées distantes
    error = pyqtSignal(str)

    def __init__(self, ip: str, port: int, user: str, password: str, remote_dir: str):
        super().__init__()
        self.ip = ip
        self.port = port
        self.user = user
        self.password = password
        self.remote_dir = remote_dir

    def run(self):
        ssh = None
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(self.ip, port=self.port, username=self.user,
                        password=self.password, timeout=10)
            sftp = ssh.open_sftp()
            entries = _list_recursive(sftp, self.remote_dir)
            sftp.close()
            self.connected.emit(entries)
        except paramiko.AuthenticationException:
            self.error.emit("Échec d'authentification — identifiant ou mot de passe incorrect.")
        except paramiko.SSHException as e:
            self.error.emit(f"Erreur SSH : {e}")
        except OSError as e:
            self.error.emit(f"Impossible de joindre {self.ip}:{self.port} — {e}")
        except Exception as e:
            self.error.emit(f"Erreur inattendue : {e}")
        finally:
            if ssh:
                try:
                    ssh.close()
                except Exception:
                    pass


class SftpDownloadWorker(QThread):
    """Téléchargement SFTP des fichiers sélectionnés vers un dossier local (thread séparé)."""

    # file_idx, file_total, filename, file_bytes_done, file_bytes_total,
    # total_bytes_done, total_bytes_all, speed_bps
    progress = pyqtSignal(int, int, str, int, int, int, int, float)
    finished = pyqtSignal(int, int)   # fichiers téléchargés, octets totaux
    error = pyqtSignal(str)

    def __init__(self, ip: str, port: int, user: str, password: str,
                 remote_files: list, local_base: str, remote_base: str):
        super().__init__()
        self.ip = ip
        self.port = port
        self.user = user
        self.password = password
        self.remote_files = remote_files
        self.local_base = local_base
        self.remote_base = remote_base.rstrip('/')

    def run(self):
        ssh = None
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(self.ip, port=self.port, username=self.user,
                        password=self.password, timeout=10)
            sftp = ssh.open_sftp()
            total_files = len(self.remote_files)

            # Récupère les tailles de tous les fichiers d'abord
            file_sizes = {}
            for rp in self.remote_files:
                try:
                    file_sizes[rp] = sftp.stat(rp).st_size or 0
                except Exception:
                    file_sizes[rp] = 0
            total_size = sum(file_sizes.values())

            total_done_ref = [0]
            last_emit_ref  = [0.0]
            start_time     = time.monotonic()
            downloaded     = 0

            for i, remote_path in enumerate(self.remote_files):
                if self.isInterruptionRequested():
                    break

                filename  = os.path.basename(remote_path)
                file_size = file_sizes[remote_path]
                rel        = remote_path[len(self.remote_base):].lstrip('/')
                local_path = os.path.join(self.local_base, rel.replace('/', os.sep))
                os.makedirs(os.path.dirname(local_path), exist_ok=True)

                # Émission initiale (0 octet transféré pour ce fichier)
                self.progress.emit(i, total_files, filename,
                                   0, file_size,
                                   total_done_ref[0], total_size, 0.0)

                prev_bytes = [0]

                def _cb(bt_done, bt_total,
                        _i=i, _fname=filename, _fsize=file_size,
                        _prev=prev_bytes):
                    delta = bt_done - _prev[0]
                    _prev[0] = bt_done
                    total_done_ref[0] += delta
                    now = time.monotonic()
                    if now - last_emit_ref[0] >= 0.08:   # ~12 Hz max
                        elapsed = now - start_time
                        speed = total_done_ref[0] / elapsed if elapsed > 0.1 else 0.0
                        self.progress.emit(_i, total_files, _fname,
                                           bt_done, bt_total,
                                           total_done_ref[0], total_size, speed)
                        last_emit_ref[0] = now

                sftp.get(remote_path, local_path, callback=_cb)
                # Garantit le compte exact après chaque fichier complet
                total_done_ref[0] = sum(file_sizes[p]
                                        for p in self.remote_files[:i + 1])
                downloaded += 1

            sftp.close()
            self.finished.emit(downloaded, total_done_ref[0])
        except paramiko.AuthenticationException:
            self.error.emit("Échec d'authentification lors du téléchargement.")
        except Exception as e:
            self.error.emit(f"Erreur de transfert : {e}")
        finally:
            if ssh:
                try:
                    ssh.close()
                except Exception:
                    pass


class SftpUploadWorker(QThread):
    """Envoi d'un fichier (bytes) vers un chemin distant via SFTP (thread séparé)."""

    finished = pyqtSignal(str)   # chemin distant effectif
    error    = pyqtSignal(str)

    def __init__(self, ip: str, port: int, user: str, password: str,
                 remote_path: str, data: bytes):
        super().__init__()
        self.ip          = ip
        self.port        = port
        self.user        = user
        self.password    = password
        self.remote_path = remote_path
        self.data        = data

    def run(self):
        ssh = None
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(self.ip, port=self.port, username=self.user,
                        password=self.password, timeout=10)
            sftp = ssh.open_sftp()
            # Créer les dossiers parents si nécessaire
            remote_dir = self.remote_path.rsplit('/', 1)[0]
            if remote_dir:
                try:
                    sftp.makedirs = None   # paramiko n'a pas makedirs
                    parts = remote_dir.lstrip('/').split('/')
                    current = '/' if remote_dir.startswith('/') else ''
                    for part in parts:
                        current = (current + '/' + part).replace('//', '/')
                        try:
                            sftp.stat(current)
                        except IOError:
                            sftp.mkdir(current)
                except Exception:
                    pass
            with sftp.file(self.remote_path, 'wb') as f:
                f.write(self.data)
            sftp.close()
            self.finished.emit(self.remote_path)
        except paramiko.AuthenticationException:
            self.error.emit("Echec d'authentification — identifiant ou mot de passe incorrect.")
        except paramiko.SSHException as e:
            self.error.emit(f"Erreur SSH : {e}")
        except OSError as e:
            self.error.emit(f"Impossible de joindre {self.ip}:{self.port} — {e}")
        except Exception as e:
            self.error.emit(f"Erreur inattendue : {e}")
        finally:
            if ssh:
                try:
                    ssh.close()
                except Exception:
                    pass


# ── Tuiles OSM ────────────────────────────────────────────────────────────────

def _lat_lng_to_tile(lat: float, lng: float, zoom: int) -> tuple:
    import math
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    x = int((lng + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def compute_tiles(waypoints, zoom_min: int, zoom_max: int, margin_km: float = 5.0):
    """Retourne la liste de tuiles (z, x, y) couvrant les waypoints + marge."""
    import math
    if not waypoints:
        return []
    lats = [p["lat"] for p in waypoints]
    lngs = [p["lng"] for p in waypoints]
    lat_min, lat_max = min(lats), max(lats)
    lng_min, lng_max = min(lngs), max(lngs)
    margin_lat = margin_km / 111.0
    mid_lat = (lat_min + lat_max) / 2.0
    margin_lng = margin_km / (111.0 * math.cos(math.radians(mid_lat))) if abs(mid_lat) < 89 else margin_lat
    lat_min -= margin_lat; lat_max += margin_lat
    lng_min -= margin_lng; lng_max += margin_lng
    tiles = []
    seen = set()
    for z in range(zoom_min, zoom_max + 1):
        x0, y0 = _lat_lng_to_tile(lat_max, lng_min, z)
        x1, y1 = _lat_lng_to_tile(lat_min, lng_max, z)
        n = 2 ** z
        x0, x1 = max(0, x0), min(n - 1, x1)
        y0, y1 = max(0, y0), min(n - 1, y1)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                key = (z, x, y)
                if key not in seen:
                    seen.add(key)
                    tiles.append(key)
    return tiles


def _sftp_makedirs(sftp, remote_path: str):
    """Crée récursivement les dossiers distants (équivalent mkdir -p)."""
    parts = remote_path.lstrip("/").split("/")
    current = "/" if remote_path.startswith("/") else ""
    for part in parts:
        current = current.rstrip("/") + "/" + part
        try:
            sftp.stat(current)
        except IOError:
            try:
                sftp.mkdir(current)
            except IOError:
                pass


class DeployWorker(QThread):
    """Envoie le JSON de waypoints puis toutes les tuiles OSM en une seule connexion SFTP."""

    log      = pyqtSignal(str)        # message horodaté pour le log textuel
    progress = pyqtSignal(int, int)   # tiles done, tiles total
    finished = pyqtSignal()
    error    = pyqtSignal(str)

    _TILE_SOURCES = [
        ("sat",      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"),
        ("seamark",  "https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png"),
    ]
    _UA = "BenthOS/1.0 (leo.bultel@imt-atlantique.fr)"

    def __init__(self, ip: str, port: int, user: str, password: str,
                 json_bytes: bytes, json_remote_path: str,
                 tiles: list, remote_tiles_dir: str):
        super().__init__()
        self.ip                = ip
        self.port              = port
        self.user              = user
        self.password          = password
        self.json_bytes        = json_bytes
        self.json_remote_path  = json_remote_path
        self.tiles             = tiles
        self.remote_tiles_dir  = remote_tiles_dir.rstrip("/")

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log.emit(f"[{ts}] {msg}")

    def run(self):
        ssh = None
        try:
            self._log(f"Connexion a {self.ip}:{self.port}...")
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(self.ip, port=self.port, username=self.user,
                        password=self.password, timeout=15)
            sftp = ssh.open_sftp()
            self._log("Connexion etablie.")

            # ── 1. Envoi du JSON de waypoints ────────────────────────────
            self._log(f"Envoi JSON : {self.json_remote_path}")
            _sftp_makedirs(sftp, self.json_remote_path.rsplit("/", 1)[0])
            with sftp.file(self.json_remote_path, "wb") as f:
                f.write(self.json_bytes)
            self._log(f"JSON envoye ({len(self.json_bytes)} octets).")

            # ── 2. Envoi des tuiles (téléchargements parallèles) ─────────
            import urllib.error
            from concurrent.futures import ThreadPoolExecutor, as_completed

            CONCURRENT = 8   # fils de téléchargement simultanés

            n_tiles = len(self.tiles)
            self._log(f"Tuiles candidates : {n_tiles} x {len(self._TILE_SOURCES)} couches = {n_tiles * len(self._TILE_SOURCES)} ({CONCURRENT} en parallele)")
            if n_tiles == 0:
                sftp.close()
                self.finished.emit()
                return

            # Pré-vérification : ne garder que les tuiles absentes du KOSMOS
            self._log("Verification des tuiles existantes sur le KOSMOS...")
            work = []
            already = 0
            for layer_name, url_tpl in self._TILE_SOURCES:
                for (z, x, y) in self.tiles:
                    remote_path = f"{self.remote_tiles_dir}/{layer_name}/{z}/{x}/{y}.png"
                    try:
                        sftp.stat(remote_path)
                        already += 1
                    except IOError:
                        work.append((layer_name, url_tpl, z, x, y))
            if already:
                self._log(f"  {already} tuile(s) deja presentes, ignorees.")
            total = len(work)
            if total == 0:
                self._log("Toutes les tuiles sont deja presentes. Rien a envoyer.")
                sftp.close()
                self.finished.emit()
                return
            self._log(f"  {total} tuile(s) manquante(s) a telecharger/envoyer.")

            ua = self._UA

            def _fetch(item):
                layer_name, url_tpl, z, x, y = item
                url = url_tpl.format(z=z, x=x, y=y)
                req = urllib.request.Request(url, headers={"User-Agent": ua})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return layer_name, z, x, y, resp.read()

            created_dirs: set[str] = set()
            sent        = 0
            skipped     = 0
            done_global = 0

            pool = ThreadPoolExecutor(max_workers=CONCURRENT)
            futures = {pool.submit(_fetch, item): item for item in work}
            try:
                for future in as_completed(futures):
                    if self.isInterruptionRequested():
                        self._log("Interrompu.")
                        break

                    done_global += 1
                    self.progress.emit(done_global, total)

                    layer_name, url_tpl, z, x, y = futures[future]
                    try:
                        _, z, x, y, tile_data = future.result()
                    except urllib.error.HTTPError as e:
                        self._log(f"  SKIP {layer_name} {z}/{x}/{y} : HTTP {e.code}")
                        skipped += 1
                        continue
                    except Exception as e:
                        self._log(f"  SKIP {layer_name} {z}/{x}/{y} : {e}")
                        skipped += 1
                        continue

                    # Valider que c'est bien une image (PNG ou JPEG)
                    if not (tile_data[:4] == b'\x89PNG' or tile_data[:3] == b'\xff\xd8\xff'):
                        self._log(f"  SKIP {layer_name} {z}/{x}/{y} : contenu invalide ({len(tile_data)} o)")
                        skipped += 1
                        continue

                    remote_dir = f"{self.remote_tiles_dir}/{layer_name}/{z}/{x}"
                    if remote_dir not in created_dirs:
                        _sftp_makedirs(sftp, remote_dir)
                        created_dirs.add(remote_dir)

                    with sftp.file(f"{remote_dir}/{y}.png", "wb") as f:
                        f.write(tile_data)
                    sent += 1

                    if sent % 50 == 0:
                        self._log(f"  {sent}/{total} tuiles envoyees...")
            finally:
                pool.shutdown(wait=False)

            self.progress.emit(total, total)
            self._log(f"Tuiles : {sent} envoyees, {skipped} ignorees.")
            sftp.close()
            self._log("Transfert termine.")
            self.finished.emit()

        except paramiko.AuthenticationException:
            self.error.emit("Echec d'authentification — identifiant ou mot de passe incorrect.")
        except paramiko.SSHException as e:
            self.error.emit(f"Erreur SSH : {e}")
        except OSError as e:
            self.error.emit(f"Impossible de joindre {self.ip}:{self.port} — {e}")
        except Exception as e:
            self.error.emit(f"Erreur inattendue : {e}")
        finally:
            if ssh:
                try:
                    ssh.close()
                except Exception:
                    pass
