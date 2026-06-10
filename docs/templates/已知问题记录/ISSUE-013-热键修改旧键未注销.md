# ISSUE-013

## 问题 ID

ISSUE-013

## 发现时间

2026-05-29

## 发现来源

Code Review / P1 / W-017 工单登记

## 所属模块

`app/hotkey.py`

## 问题描述

`HotkeyManager.set_keys()` 先将 `self._hotkey_str` 更新为新快捷键，再调用 `register()`；而 `register()` 首行会 `unregister()`。此时 `unregister()` 使用已更新的 `_hotkey_str` 调用 `keyboard.remove_hotkey`，尝试移除尚未注册的新键，而非实际已注册的旧键。用户修改全局快捷键后，旧快捷键可能仍然有效；多次修改可能累积多个全局热键钩子，导致弹幕开关被意外触发。

## 影响范围

用户可见（旧快捷键仍切换弹幕；多次修改后可能重复触发）

## 严重程度

高

## 是否阻塞当前工单

否（W-017 即为本问题的修复工单）

## 临时处理方式

重启应用（`quit()` 会调用 `unregister()`，但已泄漏的旧键在 Windows 上可能仍残留至进程完全退出；重启可清除）

## 建议后续工单

W-017（修复热键修改后旧快捷键未注销）

## 备注

- 修复：引入 `_registered_hotkey_str`，`unregister()` 按实际已注册键移除
- 触发路径：Web 控制台改热键 → `PUT /api/config` → `DanmuApp._on_config_changed` → `hotkey.set_keys()`
- 见 [W-017-完成报告](../Codex完成报告/W-017-完成报告.md)
