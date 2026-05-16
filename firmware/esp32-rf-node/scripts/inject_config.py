Import("env")

import os


def add_string_define(name: str) -> None:
    value = os.environ.get(name)
    if value:
        env.Append(CPPDEFINES=[(name, env.StringifyMacro(value))])


for key in (
    "NODE_LABEL",
    "NODE_WIFI_SSID",
    "NODE_WIFI_PASSWORD",
    "NODE_TARGET_IP",
):
    add_string_define(key)


def add_int_define(name: str) -> None:
    value = os.environ.get(name)
    if value:
        env.Append(CPPDEFINES=[(name, value)])


for key in (
    "NODE_NUM_ID",
    "NODE_TARGET_PORT",
    "NODE_TDM_SLOT",
    "NODE_TDM_TOTAL",
    "NODE_WIFI_CHANNEL",
):
    add_int_define(key)
