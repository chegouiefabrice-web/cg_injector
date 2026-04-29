"""
CG Injector — Application mobile (Kivy + KivyMD)
=================================================
Pilote deux seringues via un microcontrôleur (ESP32) en WebSocket WiFi.

Menus :
  - ACCUEIL    : configuration de la matrice T (Vol/Débit/Délai), envoi & arrêt
  - SERINGUES  : charge / décharge manuelle (appui long)
  - CONNEXION  : état + authentification (mot de passe : Poptroupe)

Communication : WebSocket bidirectionnel temps réel
  -> envoi JSON  : {"cmd": "...", ...}
  <- réception   : {"progression": x, "vol1": x, "vol2": x, ...}

Auteur : généré pour l'utilisateur — exécution Windows / VS Code.
"""

import json
import math
import threading
import time
from functools import partial

from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import (
    BooleanProperty, NumericProperty, ObjectProperty, StringProperty, ListProperty,
)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen, ScreenManager, NoTransition

from kivymd.app import MDApp
from kivymd.uix.bottomnavigation import MDBottomNavigation, MDBottomNavigationItem
from kivymd.uix.button import MDFillRoundFlatIconButton, MDRaisedButton, MDFlatButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.textfield import MDTextField
from kivymd.uix.snackbar import Snackbar

# ----------------------------------------------------------------------------
# Constantes
# ----------------------------------------------------------------------------
PASSWORD = "Poptroupe"
PERFUSEUR_DIAMETRE_MM = 3.0  # diamètre standard
PERFUSEUR_SECTION_MM2 = math.pi * (PERFUSEUR_DIAMETRE_MM / 2) ** 2

# Pour la fenêtre desktop (test sous VS Code Windows) — taille type smartphone
Window.size = (380, 760)

# ----------------------------------------------------------------------------
# Client WebSocket (thread séparé, optionnel — l'app marche sans connexion)
# ----------------------------------------------------------------------------
try:
    import websocket  # pip install websocket-client
    HAS_WS = True
except Exception:
    HAS_WS = False


class WSClient:
    """Client WebSocket simple, reconnexion automatique."""
    def __init__(self, on_message, on_status):
        self.url = "ws://192.168.4.1:81"  # IP type ESP32 AP
        self.ws = None
        self.thread = None
        self.running = False
        self.on_message = on_message
        self.on_status = on_status

    def set_url(self, url):
        self.url = url

    def connect(self):
        if not HAS_WS:
            self.on_status(False, "websocket-client non installé")
            return
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def disconnect(self):
        self.running = False
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass

    def send(self, payload: dict) -> bool:
        if not self.ws:
            return False
        try:
            self.ws.send(json.dumps(payload))
            return True
        except Exception:
            return False

    def _loop(self):
        while self.running:
            try:
                self.ws = websocket.WebSocketApp(
                    self.url,
                    on_message=lambda _w, msg: self._handle(msg),
                    on_open=lambda _w: self.on_status(True, f"Connecté à {self.url}"),
                    on_close=lambda *_a: self.on_status(False, "Déconnecté"),
                    on_error=lambda _w, e: self.on_status(False, f"Erreur: {e}"),
                )
                self.ws.run_forever(ping_interval=10, ping_timeout=5)
            except Exception as e:
                self.on_status(False, f"Connexion impossible: {e}")
            if self.running:
                time.sleep(3)  # backoff avant reconnexion

    def _handle(self, msg):
        try:
            data = json.loads(msg)
        except Exception:
            return
        self.on_message(data)


# ----------------------------------------------------------------------------
# Interface — KV
# ----------------------------------------------------------------------------
KV = '''
#:import dp kivy.metrics.dp

<TopHeader@MDBoxLayout>:
    orientation: 'horizontal'
    size_hint_y: None
    height: dp(70)
    padding: dp(8)
    spacing: dp(8)
    md_bg_color: 0.07, 0.10, 0.18, 1
    MDBoxLayout:
        orientation: 'vertical'
        MDLabel:
            text: "Seringue I"
            halign: 'center'
            theme_text_color: 'Custom'
            text_color: 0.6, 0.85, 1, 1
            font_style: 'Caption'
        MDLabel:
            id: vol1_lbl
            text: "0.00 mL"
            halign: 'center'
            theme_text_color: 'Custom'
            text_color: 1, 1, 1, 1
            font_style: 'H6'
            bold: True
    MDBoxLayout:
        orientation: 'vertical'
        MDLabel:
            text: "Seringue II"
            halign: 'center'
            theme_text_color: 'Custom'
            text_color: 0.6, 0.85, 1, 1
            font_style: 'Caption'
        MDLabel:
            id: vol2_lbl
            text: "0.00 mL"
            halign: 'center'
            theme_text_color: 'Custom'
            text_color: 1, 1, 1, 1
            font_style: 'H6'
            bold: True

<ProgressArea@MDBoxLayout>:
    orientation: 'vertical'
    size_hint_y: None
    height: dp(80)
    padding: dp(12)
    spacing: dp(4)
    MDLabel:
        text: "Progression"
        font_style: 'Caption'
        theme_text_color: 'Secondary'
    MDProgressBar:
        id: prog_bar
        value: 0
        max: 100
        color: 0.2, 0.7, 1, 1
    MDLabel:
        id: prog_lbl
        text: "0 %"
        halign: 'right'
        font_style: 'Caption'

<MatrixRow@MDBoxLayout>:
    orientation: 'horizontal'
    size_hint_y: None
    height: dp(36)
    spacing: dp(2)
'''


# ----------------------------------------------------------------------------
# App
# ----------------------------------------------------------------------------
class CGInjectorApp(MDApp):
    # État global
    progression = NumericProperty(0)
    volume1 = NumericProperty(0.0)
    volume2 = NumericProperty(0.0)
    connected = BooleanProperty(False)
    authenticated = BooleanProperty(False)
    status_text = StringProperty("Déconnecté")

    # Matrice T : liste de lignes [V1, V2, D1, D2, t, temps_calcule]
    # On stocke 6 colonnes : les 5 demandées + temps calculé pour affichage.
    matrix = ListProperty()

    # Saisie en cours
    current_row = ListProperty([None, None, None, None, None])  # V1, V2, D1, D2, t
    current_type = StringProperty("")  # "S1", "S2", "S12", "DELAI"
    line_index = NumericProperty(0)    # nombre de lignes validées (= nb de clics)

    def build(self):
        self.title = "CG Injector"
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.theme_style = "Dark"
        self.icon = "assets/icon.png"

        Builder.load_string(KV)

        self.ws = WSClient(on_message=self.on_ws_message, on_status=self.on_ws_status)

        return self._build_root()

    # --------------------- UI builders ---------------------
    def _build_root(self):
        root = MDBottomNavigation(
            panel_color=(0.05, 0.08, 0.15, 1),
            text_color_active=(0.2, 0.8, 1, 1),
            text_color_normal=(0.6, 0.6, 0.7, 1),
        )
        root.add_widget(self._tab_accueil())
        root.add_widget(self._tab_seringues())
        root.add_widget(self._tab_connexion())
        return root

    # ---------- ACCUEIL ----------
    def _tab_accueil(self):
        tab = MDBottomNavigationItem(name='accueil', text='Accueil', icon='home')

        layout = BoxLayout(orientation='vertical')

        # Header volumes
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.label import MDLabel
        from kivymd.uix.progressbar import MDProgressBar

        # --- Top : volumes seringues ---
        header = MDBoxLayout(orientation='horizontal', size_hint_y=None, height=dp(70),
                             padding=dp(8), spacing=dp(8),
                             md_bg_color=(0.07, 0.10, 0.18, 1))
        col1 = MDBoxLayout(orientation='vertical')
        col1.add_widget(MDLabel(text="Seringue I", halign='center',
                                theme_text_color='Custom',
                                text_color=(0.6, 0.85, 1, 1), font_style='Caption'))
        self.lbl_vol1 = MDLabel(text="0.00 mL", halign='center',
                                theme_text_color='Custom',
                                text_color=(1, 1, 1, 1), font_style='H6', bold=True)
        col1.add_widget(self.lbl_vol1)
        col2 = MDBoxLayout(orientation='vertical')
        col2.add_widget(MDLabel(text="Seringue II", halign='center',
                                theme_text_color='Custom',
                                text_color=(0.6, 0.85, 1, 1), font_style='Caption'))
        self.lbl_vol2 = MDLabel(text="0.00 mL", halign='center',
                                theme_text_color='Custom',
                                text_color=(1, 1, 1, 1), font_style='H6', bold=True)
        col2.add_widget(self.lbl_vol2)
        header.add_widget(col1)
        header.add_widget(col2)
        layout.add_widget(header)

        # --- Boutons de configuration ---
        btn_row = MDBoxLayout(orientation='horizontal', size_hint_y=None,
                              height=dp(50), padding=dp(6), spacing=dp(6))
        for label, key in [("Seringue I", "S1"), ("Seringue II", "S2"),
                           ("Ser I+II", "S12"), ("DELAI", "DELAI")]:
            b = MDRaisedButton(text=label, md_bg_color=(0.13, 0.45, 0.85, 1))
            b.bind(on_release=partial(self.on_config_click, key))
            btn_row.add_widget(b)
        layout.add_widget(btn_row)

        # --- Compteur ligne ---
        self.lbl_counter = MDLabel(
            text="Ligne en cours : 1   |   Lignes saisies : 0",
            halign='center', size_hint_y=None, height=dp(24),
            theme_text_color='Custom', text_color=(0.7, 0.85, 1, 1),
            font_style='Caption')
        layout.add_widget(self.lbl_counter)

        # --- Matrice (scrollable) ---
        from kivy.uix.scrollview import ScrollView
        from kivymd.uix.gridlayout import MDGridLayout
        scroll = ScrollView(size_hint=(1, 1))
        self.matrix_box = MDGridLayout(cols=1, size_hint_y=None, spacing=dp(2),
                                       padding=dp(4))
        self.matrix_box.bind(minimum_height=self.matrix_box.setter('height'))
        # En-tête matrice
        self._add_matrix_header()
        scroll.add_widget(self.matrix_box)
        layout.add_widget(scroll)

        # --- Progression ---
        prog_box = MDBoxLayout(orientation='vertical', size_hint_y=None,
                               height=dp(70), padding=dp(12), spacing=dp(4))
        prog_box.add_widget(MDLabel(text="Progression du processus",
                                    font_style='Caption',
                                    theme_text_color='Secondary'))
        self.prog_bar = MDProgressBar(value=0, max=100,
                                      color=(0.2, 0.7, 1, 1))
        prog_box.add_widget(self.prog_bar)
        self.lbl_prog = MDLabel(text="0 %", halign='right', font_style='Caption')
        prog_box.add_widget(self.lbl_prog)
        layout.add_widget(prog_box)

        # --- Boutons COMMENCER / ARRÊT ---
        action_row = MDBoxLayout(orientation='horizontal', size_hint_y=None,
                                 height=dp(60), padding=dp(8), spacing=dp(8))
        self.btn_start = MDRaisedButton(
            text="COMMENCER", md_bg_color=(0.1, 0.7, 0.3, 1),
            size_hint_x=0.5)
        self.btn_start.bind(on_release=lambda *_: self.send_matrix())
        self.btn_stop = MDRaisedButton(
            text="ARRÊT D'URGENCE", md_bg_color=(0.85, 0.15, 0.15, 1),
            size_hint_x=0.5)
        self.btn_stop.bind(on_release=lambda *_: self.emergency_stop())
        action_row.add_widget(self.btn_start)
        action_row.add_widget(self.btn_stop)
        layout.add_widget(action_row)

        tab.add_widget(layout)
        return tab

    def _add_matrix_header(self):
        from kivymd.uix.label import MDLabel
        from kivymd.uix.boxlayout import MDBoxLayout
        head = MDBoxLayout(orientation='horizontal', size_hint_y=None,
                           height=dp(28), spacing=dp(2),
                           md_bg_color=(0.10, 0.15, 0.25, 1))
        for h in ["#", "V1", "V2", "D1", "D2", "t(s)", "T calc"]:
            head.add_widget(MDLabel(text=h, halign='center',
                                    font_style='Caption', bold=True,
                                    theme_text_color='Custom',
                                    text_color=(0.7, 0.85, 1, 1)))
        head.add_widget(MDLabel(text="", size_hint_x=0.5))  # zone bouton X
        self.matrix_box.add_widget(head)

    def _refresh_matrix_view(self):
        # On vide tout (sauf header) puis on reconstruit
        self.matrix_box.clear_widgets()
        self._add_matrix_header()
        from kivymd.uix.label import MDLabel
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.button import MDIconButton
        for i, row in enumerate(self.matrix):
            line = MDBoxLayout(orientation='horizontal', size_hint_y=None,
                               height=dp(32), spacing=dp(2),
                               md_bg_color=(0.08, 0.12, 0.20, 1)
                               if i % 2 == 0 else (0.06, 0.10, 0.16, 1))
            line.add_widget(MDLabel(text=str(i + 1), halign='center',
                                    font_style='Caption'))
            for v in row[:5]:
                txt = "—" if v is None else f"{v:.2f}"
                line.add_widget(MDLabel(text=txt, halign='center',
                                        font_style='Caption'))
            tcalc = row[5]
            line.add_widget(MDLabel(
                text="—" if tcalc is None else f"{tcalc:.2f}s",
                halign='center', font_style='Caption',
                theme_text_color='Custom',
                text_color=(0.4, 1, 0.6, 1)))
            del_btn = MDIconButton(icon="close", size_hint_x=0.5,
                                   theme_icon_color='Custom',
                                   icon_color=(1, 0.4, 0.4, 1))
            del_btn.bind(on_release=partial(self.delete_row, i))
            line.add_widget(del_btn)
            self.matrix_box.add_widget(line)

    # ---------- SERINGUES ----------
    def _tab_seringues(self):
        tab = MDBottomNavigationItem(name='seringues', text='Seringues',
                                     icon='needle')
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.label import MDLabel
        layout = MDBoxLayout(orientation='vertical', padding=dp(12), spacing=dp(12))
        layout.add_widget(MDLabel(
            text="Contrôle manuel — appuis longs",
            halign='center', font_style='H6',
            size_hint_y=None, height=dp(40)))

        for sid in (1, 2):
            box = MDBoxLayout(orientation='vertical', spacing=dp(8),
                              padding=dp(12), md_bg_color=(0.08, 0.12, 0.20, 1),
                              radius=[dp(12)])
            box.add_widget(MDLabel(text=f"Seringue {'I' * sid}",
                                   font_style='H6', halign='center',
                                   size_hint_y=None, height=dp(30)))
            row = MDBoxLayout(orientation='horizontal', spacing=dp(10),
                              size_hint_y=None, height=dp(80))
            btn_load = MDRaisedButton(text="CHARGER ▲",
                                      md_bg_color=(0.1, 0.6, 0.85, 1),
                                      size_hint=(0.5, 1))
            btn_unload = MDRaisedButton(text="VIDER ▼",
                                        md_bg_color=(0.85, 0.45, 0.1, 1),
                                        size_hint=(0.5, 1))
            self._bind_long_press(btn_load, sid, "load")
            self._bind_long_press(btn_unload, sid, "unload")
            row.add_widget(btn_load)
            row.add_widget(btn_unload)
            box.add_widget(row)
            layout.add_widget(box)

        tab.add_widget(layout)
        return tab

    def _bind_long_press(self, btn, syringe_id, action):
        """Envoie 'start' à on_press, 'stop' à on_release. Le micro bouge tant
        que l'utilisateur appuie."""
        def on_press(*_):
            self.send_cmd({"cmd": f"manual_{action}", "syringe": syringe_id,
                           "state": "start"})
        def on_release(*_):
            self.send_cmd({"cmd": f"manual_{action}", "syringe": syringe_id,
                           "state": "stop"})
        btn.bind(on_press=on_press, on_release=on_release)

    # ---------- CONNEXION ----------
    def _tab_connexion(self):
        tab = MDBottomNavigationItem(name='connexion', text='Connexion',
                                     icon='wifi')
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.label import MDLabel
        layout = MDBoxLayout(orientation='vertical', padding=dp(16), spacing=dp(12))

        layout.add_widget(MDLabel(text="État de la connexion",
                                  font_style='H6',
                                  size_hint_y=None, height=dp(40)))
        self.lbl_status = MDLabel(text="● Déconnecté",
                                  theme_text_color='Custom',
                                  text_color=(1, 0.4, 0.4, 1),
                                  size_hint_y=None, height=dp(28))
        layout.add_widget(self.lbl_status)

        self.tf_url = MDTextField(
            hint_text="Adresse WebSocket (ex: ws://192.168.4.1:81)",
            text="ws://192.168.4.1:81",
            size_hint_y=None, height=dp(60))
        layout.add_widget(self.tf_url)

        self.tf_pwd = MDTextField(
            hint_text="Mot de passe",
            password=True,
            size_hint_y=None, height=dp(60))
        layout.add_widget(self.tf_pwd)

        btn_connect = MDRaisedButton(text="CONNECTER & AUTHENTIFIER",
                                     pos_hint={'center_x': 0.5},
                                     md_bg_color=(0.1, 0.6, 0.85, 1))
        btn_connect.bind(on_release=lambda *_: self.do_connect())
        layout.add_widget(btn_connect)

        btn_disc = MDFlatButton(text="Déconnecter",
                                pos_hint={'center_x': 0.5})
        btn_disc.bind(on_release=lambda *_: self.do_disconnect())
        layout.add_widget(btn_disc)

        layout.add_widget(MDLabel(text="", size_hint_y=1))  # spacer

        info = ("Le mot de passe est vérifié côté microcontrôleur.\n"
                "Aucune commande n'est envoyée tant que l'authentification\n"
                "n'a pas été confirmée.")
        layout.add_widget(MDLabel(text=info, font_style='Caption',
                                  theme_text_color='Secondary',
                                  size_hint_y=None, height=dp(60)))

        tab.add_widget(layout)
        return tab

    # --------------------- Logique configuration ---------------------
    def on_config_click(self, key, *_):
        # Empêche de cliquer ailleurs tant que la ligne n'est pas terminée
        if self.current_type and not self._row_complete():
            self._snack("Terminez d'abord la saisie en cours.")
            return
        self.current_type = key
        if key == "S1":
            self._ask_values([("V1 (mL)", 0), ("D1 (mL/s)", 2)])
        elif key == "S2":
            self._ask_values([("V2 (mL)", 1), ("D2 (mL/s)", 3)])
        elif key == "S12":
            self._ask_values([("V1 (mL)", 0), ("V2 (mL)", 1), ("D2 (mL/s)", 3)])
        elif key == "DELAI":
            self._ask_values([("t délai (s)", 4)])

    def _row_complete(self):
        # Considère la ligne complète quand current_type a été validé
        return self.current_type == ""

    def _ask_values(self, fields):
        """Ouvre une dialog avec les champs (label, index_dans_current_row)."""
        from kivymd.uix.boxlayout import MDBoxLayout
        content = MDBoxLayout(orientation='vertical', spacing=dp(8),
                              size_hint_y=None, height=dp(80) * len(fields))
        text_fields = []
        for label, idx in fields:
            tf = MDTextField(hint_text=label, input_filter='float',
                             helper_text="2 décimales (ex: 12.34)",
                             helper_text_mode="on_focus")
            content.add_widget(tf)
            text_fields.append((tf, idx))

        def on_validate(*_):
            new_row = list(self.current_row)
            for tf, idx in text_fields:
                try:
                    val = float(tf.text)
                    val = round(val, 2)  # 10^-2 près
                except Exception:
                    self._snack(f"Valeur invalide : {tf.hint_text}")
                    return
                new_row[idx] = val
            self.current_row = new_row
            dialog.dismiss()
            self._commit_row()

        def on_cancel(*_):
            dialog.dismiss()
            self.current_type = ""
            self._snack("Saisie annulée")

        dialog = MDDialog(
            title="Renseignez les valeurs",
            type="custom",
            content_cls=content,
            buttons=[
                MDFlatButton(text="ANNULER", on_release=on_cancel),
                MDRaisedButton(text="VALIDER", on_release=on_validate),
            ],
        )
        dialog.open()

    def _commit_row(self):
        """Termine la saisie actuelle, calcule t et range dans la matrice."""
        v1, v2, d1, d2, t = self.current_row
        tcalc = None
        # Calcul du temps en fonction du type
        if self.current_type == "S1" and v1 is not None and d1 not in (None, 0):
            tcalc = v1 / d1
        elif self.current_type == "S2" and v2 is not None and d2 not in (None, 0):
            tcalc = v2 / d2
        elif self.current_type == "S12" and v1 is not None and v2 is not None \
                and d2 not in (None, 0):
            tcalc = (v1 + v2) / d2
        elif self.current_type == "DELAI" and t is not None:
            tcalc = t  # le délai EST le temps

        # Selon les règles : on ne renseigne pas T calc pour les lignes "DELAI"
        # (juste un temps). On le met quand même pour visibilité, mais avec
        # une marque visuelle équivalente.
        row = [v1, v2, d1, d2, t, tcalc]
        self.matrix = self.matrix + [row]
        self.line_index = len(self.matrix)
        self.current_row = [None, None, None, None, None]
        self.current_type = ""
        self.lbl_counter.text = (
            f"Ligne en cours : {self.line_index + 1}   |   "
            f"Lignes saisies : {self.line_index}"
        )
        self._refresh_matrix_view()

    def delete_row(self, idx, *_):
        if 0 <= idx < len(self.matrix):
            new = list(self.matrix)
            del new[idx]
            self.matrix = new
            self.line_index = len(self.matrix)
            self.lbl_counter.text = (
                f"Ligne en cours : {self.line_index + 1}   |   "
                f"Lignes saisies : {self.line_index}"
            )
            self._refresh_matrix_view()

    # --------------------- Envoi vers ESP32 ---------------------
    def send_matrix(self):
        if not self.matrix:
            self._snack("Matrice vide.")
            return
        if not self.authenticated:
            self._snack("Connectez-vous et authentifiez-vous d'abord.")
            return
        # On envoie uniquement les 5 colonnes "logiques"
        payload = {
            "cmd": "start",
            "matrix": [[None if v is None else round(v, 2) for v in row[:5]]
                       for row in self.matrix],
        }
        if self.send_cmd(payload):
            self._snack("Matrice envoyée — démarrage demandé.")

    def emergency_stop(self):
        ok = self.send_cmd({"cmd": "emergency_stop"})
        self._snack("ARRÊT D'URGENCE envoyé." if ok
                    else "Aucune connexion — arrêt impossible.")

    def send_cmd(self, payload: dict) -> bool:
        if not self.connected:
            self._snack("Pas connecté.")
            return False
        ok = self.ws.send(payload)
        if not ok:
            self._snack("Échec d'envoi.")
        return ok

    # --------------------- Connexion ---------------------
    def do_connect(self):
        url = (self.tf_url.text or "").strip()
        pwd = (self.tf_pwd.text or "").strip()
        if not url:
            self._snack("URL manquante."); return
        if pwd != PASSWORD:
            self._snack("Mot de passe incorrect."); return
        self.ws.set_url(url)
        self.ws.connect()
        # On enverra le mot de passe au serveur dès la connexion
        self._pending_auth_password = pwd

    def do_disconnect(self):
        self.ws.disconnect()
        self.connected = False
        self.authenticated = False
        self._update_status_label()

    def on_ws_status(self, ok, msg):
        # Appelé depuis un thread WS -> on doit revenir au thread principal
        Clock.schedule_once(lambda dt: self._apply_ws_status(ok, msg), 0)

    def _apply_ws_status(self, ok, msg):
        self.connected = ok
        self.status_text = msg
        self._update_status_label()
        if ok and getattr(self, "_pending_auth_password", None):
            self.ws.send({"cmd": "auth", "password": self._pending_auth_password})
            self._pending_auth_password = None

    def _update_status_label(self):
        if not hasattr(self, "lbl_status"):
            return
        if self.connected and self.authenticated:
            self.lbl_status.text = f"● Connecté & authentifié — {self.status_text}"
            self.lbl_status.text_color = (0.3, 1, 0.4, 1)
        elif self.connected:
            self.lbl_status.text = f"● Connecté (non auth.) — {self.status_text}"
            self.lbl_status.text_color = (1, 0.85, 0.3, 1)
        else:
            self.lbl_status.text = f"● Déconnecté — {self.status_text}"
            self.lbl_status.text_color = (1, 0.4, 0.4, 1)

    # --------------------- Réception WS ---------------------
    @mainthread
    def on_ws_message(self, data: dict):
        if "auth" in data:
            self.authenticated = bool(data["auth"])
            self._update_status_label()
            self._snack("Authentification OK" if self.authenticated
                        else "Authentification refusée")
        if "progression" in data:
            try:
                p = float(data["progression"])
                self.progression = max(0.0, min(100.0, p))
                self.prog_bar.value = self.progression
                self.lbl_prog.text = f"{self.progression:.0f} %"
            except Exception:
                pass
        if "vol1" in data:
            try:
                self.volume1 = float(data["vol1"])
                self.lbl_vol1.text = f"{self.volume1:.2f} mL"
            except Exception:
                pass
        if "vol2" in data:
            try:
                self.volume2 = float(data["vol2"])
                self.lbl_vol2.text = f"{self.volume2:.2f} mL"
            except Exception:
                pass

    # --------------------- Utilitaires ---------------------
    def _snack(self, text):
        try:
            Snackbar(text=text, duration=2).open()
        except Exception:
            print("[snack]", text)


if __name__ == "__main__":
    CGInjectorApp().run()

