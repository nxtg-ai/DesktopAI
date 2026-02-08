#Requires AutoHotkey v2.0
#SingleInstance Force
Persistent
SendMode "Input"
SetKeyDelay -1, 30

; ---------------------------
; Config
; ---------------------------
INTERVAL_MS := 10 * 60 * 1000
MESSAGE := "continue intelligently"
SUBMIT_KEY := "{Enter}"
; If your target app requires Ctrl+Enter to submit, set:
; SUBMIT_KEY := "^{Enter}"
TYPE_SETTLE_MS := 120

; Optional safety gate:
; Set to part of the target window title (example: "DesktopAI [WSL")
; Leave empty to send to whichever control is currently focused.
TARGET_WINDOW_SUBSTR := "Visual Studio Code"
TARGET_PROCESS_EXE := "Code.exe"

; Set true to send once immediately when loop starts.
SEND_IMMEDIATELY := true

; ---------------------------
; Runtime
; ---------------------------
isRunning := false

SendMessageNow(*) {
    global TARGET_WINDOW_SUBSTR, TARGET_PROCESS_EXE, MESSAGE, SUBMIT_KEY, TYPE_SETTLE_MS

    if !IsTargetWindowActive() {
        TrayTip("Continue Loop", "Skipped (target window/process mismatch).", 1)
        return
    }

    SendText(MESSAGE)
    Sleep TYPE_SETTLE_MS
    Send(SUBMIT_KEY)
    TrayTip("Continue Loop", "Sent: " MESSAGE " + " SUBMIT_KEY, 1)
}

IsTargetWindowActive() {
    global TARGET_WINDOW_SUBSTR, TARGET_PROCESS_EXE

    activeTitle := WinGetTitle("A")
    activeExe := WinGetProcessName("A")

    if (TARGET_PROCESS_EXE != "" && activeExe != TARGET_PROCESS_EXE) {
        return false
    }
    if (TARGET_WINDOW_SUBSTR != "" && !InStr(activeTitle, TARGET_WINDOW_SUBSTR)) {
        return false
    }
    return true
}

StartLoop() {
    global isRunning, INTERVAL_MS, SEND_IMMEDIATELY
    if isRunning {
        return
    }
    isRunning := true
    SetTimer(SendMessageNow, INTERVAL_MS)
    if SEND_IMMEDIATELY {
        SendMessageNow()
    }
    TrayTip("Continue Loop", "Started (every 10 minutes).", 1)
}

StopLoop() {
    global isRunning
    if !isRunning {
        return
    }
    isRunning := false
    SetTimer(SendMessageNow, 0)
    TrayTip("Continue Loop", "Stopped.", 1)
}

ToggleLoop() {
    global isRunning
    if isRunning {
        StopLoop()
    } else {
        StartLoop()
    }
}

; ---------------------------
; Hotkeys
; ---------------------------
; Ctrl+Alt+S -> start/stop loop
^!s::ToggleLoop()

; Ctrl+Alt+E -> send once now
^!e::SendMessageNow()

; Ctrl+Alt+Q -> quit script
^!q::ExitApp()

; Auto-start loop on launch
StartLoop()
