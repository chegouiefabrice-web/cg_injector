# CG Injector — Application mobile (Python / Kivy)

Application de pilotage de deux seringues motorisées via un microcontrôleur
(ESP32) en WebSocket WiFi.

## 📦 Contenu

```
cg_injector/
├── main.py                    # Application principale (Kivy + KivyMD)
├── requirements.txt           # Dépendances Python
├── buildozer.spec             # Configuration packaging APK Android
├── assets/
│   └── icon.png               # Icône de l'application
├── firmware_example/
│   └── esp32_websocket.ino    # Exemple firmware ESP32
└── README.md
```

## 🪟 Lancer sur Windows depuis VS Code

1. **Installer Python 3.10 ou 3.11** (recommandé) depuis https://www.python.org/.
   Cocher *Add Python to PATH*.
2. Ouvrir le dossier `cg_injector` dans **VS Code** (`File → Open Folder`).
3. Ouvrir un terminal (`Ctrl+ù`) et créer un environnement virtuel :
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```
4. Lancer l'application :
   ```powershell
   python main.py
   ```
   Une fenêtre au format smartphone (380×760) s'ouvre.

> 💡 Si une dépendance refuse de s'installer (rare sur Windows), installer
> *Microsoft C++ Build Tools* puis relancer `pip install`.

## 📱 Packager en APK Android

Le packaging Android via **Buildozer** ne fonctionne **que sur Linux / WSL**.
Sous Windows, installer **WSL2 (Ubuntu)** puis :

```bash
sudo apt update && sudo apt install -y python3-pip openjdk-17-jdk \
    git zip unzip autoconf libtool pkg-config zlib1g-dev \
    libncurses5-dev libncursesw5-dev libtinfo6 cmake libffi-dev libssl-dev
pip install --user buildozer cython==0.29.36
cd /mnt/c/.../cg_injector
buildozer -v android debug
```

L'APK est généré dans `bin/`.

## 🔌 Communication

| Sens                | Format JSON envoyé                                              |
|---------------------|-----------------------------------------------------------------|
| App → ESP32 (auth)  | `{"cmd":"auth","password":"Poptroupe"}`                         |
| ESP32 → App (auth)  | `{"auth":true}`                                                 |
| App → ESP32 (start) | `{"cmd":"start","matrix":[[V1,V2,D1,D2,t], ...]}`               |
| App → ESP32 (stop)  | `{"cmd":"emergency_stop"}`                                      |
| App → ESP32 manuel  | `{"cmd":"manual_load","syringe":1,"state":"start"\|"stop"}`     |
| ESP32 → App (live)  | `{"progression":42.0,"vol1":12.50,"vol2":8.30}`                 |

L'authentification (mot de passe **Poptroupe**) est vérifiée **côté
microcontrôleur** : tant qu'elle n'est pas confirmée, le firmware ignore les
commandes.

## 🧪 Tester sans microcontrôleur

L'application fonctionne sans connexion : vous pouvez naviguer, configurer la
matrice, supprimer des lignes, etc. Les boutons COMMENCER / ARRÊT afficheront
un message si aucune connexion n'est active.

Pour simuler un ESP32 sur votre PC, vous pouvez utiliser le mini-serveur
Python suivant (sauvegardez en `mock_server.py` et lancez `python mock_server.py`,
puis dans l'app utilisez `ws://127.0.0.1:8765`) :

```python
import asyncio, json, websockets
async def handler(ws):
    async def pub():
        p = 0
        while True:
            await ws.send(json.dumps({"progression": p, "vol1": 10-p/20, "vol2": 5+p/30}))
            p = (p+1) % 101
            await asyncio.sleep(1)
    task = asyncio.create_task(pub())
    try:
        async for msg in ws:
            data = json.loads(msg); print("RX", data)
            if data.get("cmd") == "auth":
                await ws.send(json.dumps({"auth": data.get("password")=="Poptroupe"}))
    finally:
        task.cancel()
asyncio.run(websockets.serve(handler, "0.0.0.0", 8765).__await__().__next__() or asyncio.Future())
```
(installez `pip install websockets` au préalable)

## 🧮 Règles métier implémentées

- Matrice **T** à **5 colonnes** : `V1, V2, D1, D2, t` + colonne calculée
  `T_calc` (visible dans l'app).
- Boutons :
  - **Seringue I** → renseigne **V1, D1** (col. 1 & 3)
  - **Seringue II** → renseigne **V2, D2** (col. 2 & 4)
  - **Seringue I+II** → renseigne **V1, V2, D2** (col. 1, 2, 4)
  - **DELAI** → renseigne **t** (col. 5)
- Calcul du temps : `T = V / D` (en secondes ; pour I+II : `T = (V1+V2)/D2`).
- Saisie limitée à **2 décimales** (10⁻²).
- Impossible de cliquer un autre bouton tant que la saisie n'est pas validée
  ou annulée.
- Annulation possible (bouton ANNULER) ou suppression d'une ligne complète
  (icône ✕ dans la matrice).
- COMMENCER → envoie la matrice complète en WebSocket.
- ARRÊT D'URGENCE → envoie une commande d'arrêt immédiat.
- Onglet SERINGUES → contrôle manuel **en appui long** (charge / décharge).
- Onglet CONNEXION → URL WebSocket + mot de passe **Poptroupe**.

## 🎨 Icône

Voir `assets/icon.png` — "CG" en grand caractères chromés avec halo cyan,
"injector" en dessous avec effet miroir/inversé sur fond bleu nuit.
