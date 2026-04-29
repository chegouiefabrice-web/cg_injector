[app]
title = CG Injector
package.name = cginjector
package.domain = org.cg
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 1.0
requirements = python3,kivy==2.3.0,kivymd==1.2.0,websocket-client,certifi
icon.filename = %(source.dir)s/assets/icon.png
orientation = portrait
fullscreen = 0
android.permissions = INTERNET, ACCESS_WIFI_STATE, ACCESS_NETWORK_STATE
android.api = 33
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
osx.python_version = 3
osx.kivy_version = 2.3.0

[buildozer]
log_level = 2
warn_on_root = 1
