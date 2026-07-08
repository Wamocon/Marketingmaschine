from __future__ import annotations


def render_marketing_console() -> str:
    return """<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WAMOCON Marketing-Konsole</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f3;
      --surface: #ffffff;
      --surface-2: #eef4f2;
      --surface-3: #e7ece7;
      --ink: #14201f;
      --muted: #60706b;
      --line: #d6dfdb;
      --line-strong: #b7c6c1;
      --teal: #007c72;
      --teal-dark: #07534d;
      --mint: #d9f4ea;
      --blue: #315f9f;
      --amber: #a55b08;
      --orange: #d46a2c;
      --red: #b42318;
      --green: #178044;
      --shadow: 0 18px 50px rgba(22, 32, 31, 0.10);
      --soft-shadow: 0 10px 28px rgba(22, 32, 31, 0.08);
      --radius: 8px;
      --radius-sm: 6px;
      --focus: #2459d3;
      --mono: "Cascadia Mono", "SFMono-Regular", Consolas, monospace;
      --sans: Aptos, "Segoe UI", system-ui, sans-serif;
    }

    body.theme-dark {
      color-scheme: dark;
      --bg: #101615;
      --surface: #17201f;
      --surface-2: #1f2b29;
      --surface-3: #263432;
      --ink: #edf5f2;
      --muted: #aab9b4;
      --line: #31413e;
      --line-strong: #4a625c;
      --teal: #30c4b2;
      --teal-dark: #9fe7dc;
      --mint: #173c36;
      --blue: #8fb4f6;
      --amber: #f2b45f;
      --orange: #f59b62;
      --red: #ff897f;
      --green: #75d995;
      --shadow: 0 20px 56px rgba(0, 0, 0, 0.35);
      --soft-shadow: 0 12px 32px rgba(0, 0, 0, 0.25);
    }

    * { box-sizing: border-box; }

    html {
      min-width: 320px;
      background: var(--bg);
    }

    body {
      margin: 0;
      background:
        linear-gradient(180deg, rgba(0, 124, 114, 0.08), transparent 260px),
        var(--bg);
      color: var(--ink);
      font-family: var(--sans);
      font-size: 14px;
      line-height: 1.45;
      overflow-x: hidden;
    }

    button, input, select, textarea {
      font: inherit;
      min-width: 0;
    }

    button {
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      background: var(--surface);
      color: var(--ink);
      cursor: pointer;
      transition: transform 160ms ease, border-color 160ms ease, background 160ms ease, box-shadow 160ms ease;
    }

    button:hover {
      transform: translateY(-1px);
      box-shadow: 0 7px 18px rgba(20, 32, 31, 0.10);
      border-color: var(--line-strong);
    }

    button:active { transform: translateY(0); }

    button:focus-visible,
    input:focus-visible,
    select:focus-visible,
    textarea:focus-visible {
      outline: 2px solid var(--focus);
      outline-offset: 2px;
    }

    .app {
      min-height: 100vh;
      width: 100%;
      max-width: 100vw;
      overflow-x: hidden;
      display: grid;
      grid-template-rows: auto 1fr;
    }

    .topbar {
      position: sticky;
      top: 0;
      z-index: 20;
      width: 100%;
      max-width: 100vw;
      display: grid;
      grid-template-columns: minmax(280px, 1fr) auto;
      gap: 18px;
      align-items: center;
      padding: 14px 22px;
      background: rgba(244, 246, 243, 0.92);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(14px);
    }

    .theme-dark .topbar {
      background: rgba(16, 22, 21, 0.92);
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }

    .brand > div {
      min-width: 0;
    }

    .mark {
      width: 40px;
      height: 40px;
      flex: 0 0 40px;
      border-radius: 8px;
      background: linear-gradient(135deg, var(--teal), var(--orange));
      display: grid;
      place-items: center;
      color: #ffffff;
      font-weight: 800;
      box-shadow: var(--soft-shadow);
    }

    h1, h2, h3, p {
      margin: 0;
      letter-spacing: 0;
    }

    h1 {
      font-size: 20px;
      line-height: 1.15;
      font-weight: 760;
      overflow-wrap: anywhere;
    }

    h2 {
      font-size: 20px;
      font-weight: 740;
    }

    h3 {
      font-size: 14px;
      font-weight: 720;
    }

    .subtle {
      color: var(--muted);
      font-size: 13px;
      overflow-wrap: anywhere;
    }

    .top-actions {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      justify-content: flex-end;
      min-width: 0;
    }

    .language-select {
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      background: var(--surface);
      color: var(--ink);
      padding: 8px 10px;
      font-weight: 700;
    }

    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      padding: 8px 11px;
      font-weight: 700;
      white-space: nowrap;
    }

    .btn-primary {
      background: var(--teal);
      color: #ffffff;
      border-color: var(--teal);
    }

    .btn-secondary {
      background: var(--surface);
      color: var(--ink);
    }

    .btn-danger {
      background: #fff5f3;
      color: var(--red);
      border-color: #f4c2bd;
    }

    .theme-dark .btn-danger {
      background: #371b19;
      border-color: #6b302b;
    }

    .icon {
      width: 16px;
      height: 16px;
      stroke: currentColor;
      stroke-width: 2;
      fill: none;
      stroke-linecap: round;
      stroke-linejoin: round;
      flex: 0 0 auto;
    }

    .layout {
      display: grid;
      grid-template-columns: 318px minmax(0, 1fr);
      gap: 18px;
      padding: 18px;
      max-width: 100vw;
      min-width: 0;
    }

    .sidebar {
      position: sticky;
      top: 80px;
      align-self: start;
      min-width: 0;
      max-height: calc(100vh - 98px);
      overflow: auto;
      display: grid;
      gap: 12px;
    }

    .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--soft-shadow);
      min-width: 0;
    }

    .panel-body {
      padding: 14px;
      min-width: 0;
      overflow-x: auto;
    }

    .panel-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 14px 14px 0;
    }

    .workspace {
      min-width: 0;
      display: grid;
      gap: 14px;
    }

    .hero-strip {
      display: grid;
      grid-template-columns: minmax(360px, 1.6fr) minmax(260px, 0.55fr);
      gap: 14px;
      align-items: stretch;
    }

    .command-panel {
      min-height: 286px;
      display: grid;
      grid-template-columns: minmax(260px, 0.95fr) minmax(260px, 0.85fr);
      overflow: hidden;
      position: relative;
      isolation: isolate;
      background: #fdfefe;
    }

    .command-panel::after {
      content: "";
      position: absolute;
      inset: auto 18px 0 18px;
      height: 3px;
      background: linear-gradient(90deg, var(--teal), var(--blue), var(--orange));
      opacity: 0.85;
    }

    .command-copy {
      max-width: 760px;
      padding: 22px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 18px;
      position: relative;
      z-index: 2;
    }

    .hero-kicker {
      color: var(--teal-dark);
      font-weight: 800;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 8px;
    }

    .hero-title {
      font-size: 30px;
      line-height: 1.05;
      max-width: 620px;
      margin-bottom: 10px;
    }

    .hero-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .hero-visual {
      min-height: 100%;
      position: relative;
      overflow: hidden;
      border-left: 1px solid var(--line);
      background: var(--surface-2);
    }

    .hero-visual img {
      width: 100%;
      height: 100%;
      min-height: 286px;
      object-fit: cover;
      display: block;
      transform: scale(1.02);
      animation: heroDrift 9s ease-in-out infinite alternate;
    }

    .hero-visual::after {
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(90deg, rgba(255,255,255,0.08), rgba(255,255,255,0));
      pointer-events: none;
    }

    @keyframes heroDrift {
      from { transform: scale(1.02) translateX(0); }
      to { transform: scale(1.06) translateX(-8px); }
    }

    .operator-queue {
      display: grid;
      gap: 10px;
      padding: 12px;
    }

    .queue-item {
      min-height: 62px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      background: var(--surface);
      display: grid;
      gap: 4px;
      animation: enter 260ms ease both;
    }

    .queue-item small {
      color: var(--muted);
      font-size: 12px;
    }

    .queue-item strong {
      font-size: 18px;
      line-height: 1;
    }

    .metric-grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
    }

    .metric {
      padding: 13px;
      min-height: 88px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--soft-shadow);
    }

    .metric small {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 8px;
    }

    .metric strong {
      font-size: 20px;
      line-height: 1.1;
    }

    .metric span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-top: 6px;
    }

    .step-list {
      display: grid;
      gap: 8px;
    }

    .step {
      display: grid;
      grid-template-columns: 28px minmax(0, 1fr);
      gap: 9px;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      background: var(--surface-2);
    }

    .step-number {
      width: 28px;
      height: 28px;
      border-radius: 7px;
      background: var(--ink);
      color: var(--surface);
      display: grid;
      place-items: center;
      font-weight: 800;
      font-size: 12px;
    }

    .step strong {
      display: block;
      font-size: 13px;
      overflow-wrap: anywhere;
    }

    .step span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-top: 2px;
      overflow-wrap: anywhere;
    }

    .nav-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }

    .nav-tab {
      min-height: 54px;
      display: flex;
      align-items: center;
      gap: 9px;
      padding: 9px;
      text-align: left;
      background: var(--surface);
    }

    .nav-tab .tab-copy {
      min-width: 0;
    }

    .nav-tab strong {
      display: block;
      font-size: 13px;
    }

    .nav-tab span {
      display: block;
      color: var(--muted);
      font-size: 11px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .nav-tab[aria-selected="true"] {
      border-color: #8ed4ca;
      background: var(--mint);
      color: var(--teal-dark);
      box-shadow: inset 0 0 0 1px rgba(0, 124, 114, 0.22);
    }

    .tool-links {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }

    .tool-links a {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      min-height: 38px;
      padding: 8px 10px;
      color: var(--ink);
      text-decoration: none;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      background: var(--surface);
      transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
    }

    .tool-links a:hover {
      transform: translateY(-1px);
      border-color: var(--line-strong);
      background: var(--surface-2);
    }

    .status-row {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      align-items: center;
    }

    .pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 26px;
      padding: 4px 8px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }

    .pill::before {
      content: "";
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: currentColor;
    }

    .pill.ok { color: var(--green); background: rgba(23, 128, 68, 0.10); border-color: rgba(23, 128, 68, 0.25); }
    .pill.warn { color: var(--amber); background: rgba(165, 91, 8, 0.10); border-color: rgba(165, 91, 8, 0.26); }
    .pill.bad { color: var(--red); background: rgba(180, 35, 24, 0.10); border-color: rgba(180, 35, 24, 0.25); }
    .pill.neutral { color: var(--blue); background: rgba(49, 95, 159, 0.10); border-color: rgba(49, 95, 159, 0.25); }

    .recent-toolbar {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      margin: 10px 0;
    }

    .recent-list {
      display: grid;
      gap: 7px;
      max-height: 420px;
      overflow: auto;
      padding-right: 2px;
    }

    .recent-item {
      min-height: 64px;
      width: 100%;
      text-align: left;
      padding: 9px;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      background: var(--surface);
      display: grid;
      gap: 4px;
    }

    .recent-item strong {
      display: block;
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 13px;
    }

    .recent-item span {
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }

    .screen {
      display: none;
      min-width: 0;
      max-width: 100%;
      animation: enter 260ms ease both;
    }

    .screen.active { display: block; }

    @keyframes enter {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }

    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: 1ms !important;
        transition-duration: 1ms !important;
        scroll-behavior: auto !important;
      }
    }

    .screen-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 12px;
      min-width: 0;
    }

    .screen-head p {
      color: var(--muted);
      margin-top: 5px;
      max-width: 780px;
    }

    .form-grid {
      display: grid;
      grid-template-columns: minmax(340px, 1.05fr) minmax(320px, 0.95fr);
      gap: 14px;
    }

    .wide-grid {
      display: grid;
      grid-template-columns: minmax(320px, 0.9fr) minmax(340px, 1.1fr);
      gap: 14px;
    }

    .stack {
      display: grid;
      gap: 14px;
    }

    .field-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }

    label {
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      margin: 10px 0 5px;
    }

    input, select, textarea {
      width: 100%;
      min-height: 40px;
      border: 1px solid var(--line-strong);
      border-radius: var(--radius-sm);
      background: var(--surface);
      color: var(--ink);
      padding: 9px 10px;
    }

    textarea {
      min-height: 96px;
      resize: vertical;
    }

    .input-with-action {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: end;
    }

    .section-title {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 2px;
    }

    .section-title .badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 24px;
      height: 24px;
      border-radius: 7px;
      background: var(--surface-2);
      color: var(--teal-dark);
      font-size: 12px;
      font-weight: 800;
      border: 1px solid var(--line);
    }

    .quality {
      display: grid;
      gap: 9px;
    }

    .quality-meter {
      height: 10px;
      border-radius: 999px;
      background: var(--surface-3);
      overflow: hidden;
      border: 1px solid var(--line);
    }

    .quality-meter span {
      display: block;
      height: 100%;
      width: 0;
      background: linear-gradient(90deg, var(--orange), var(--teal));
      transition: width 220ms ease;
    }

    .checklist {
      display: grid;
      gap: 7px;
    }

    .check {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 8px 9px;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      background: var(--surface-2);
      color: var(--muted);
      font-size: 12px;
    }

    .check.ok {
      color: var(--green);
      border-color: rgba(23, 128, 68, 0.25);
      background: rgba(23, 128, 68, 0.08);
    }

    .check.bad {
      color: var(--red);
      border-color: rgba(180, 35, 24, 0.25);
      background: rgba(180, 35, 24, 0.08);
    }

    .checkbox-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(130px, 1fr));
      gap: 8px;
      margin-top: 12px;
    }

    .checkbox-grid label {
      margin: 0;
      display: flex;
      gap: 8px;
      align-items: center;
      color: var(--ink);
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      background: var(--surface-2);
    }

    .checkbox-grid input {
      width: 18px;
      min-height: 18px;
      padding: 0;
      flex: 0 0 auto;
    }

    .result-panel {
      display: grid;
      grid-template-rows: auto minmax(240px, 1fr);
      min-height: 420px;
    }

    .result-toolbar {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: center;
      padding: 14px;
      border-bottom: 1px solid var(--line);
    }

    pre {
      margin: 0;
      padding: 14px;
      background: #10201f;
      color: #e8f5f2;
      font-family: var(--mono);
      font-size: 12px;
      line-height: 1.55;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      border-radius: 0 0 var(--radius) var(--radius);
    }

    .theme-dark pre {
      background: #0b1110;
    }

    #trendRunResult,
    #trendConceptResult,
    #postPreview,
    #approvalResult,
    #schedulerPreview {
      background: var(--surface-2);
      color: var(--ink);
      font-family: var(--sans);
      font-size: 13px;
      line-height: 1.62;
    }

    .theme-dark #trendRunResult,
    .theme-dark #trendConceptResult,
    .theme-dark #postPreview,
    .theme-dark #approvalResult,
    .theme-dark #schedulerPreview {
      background: var(--surface-2);
      color: var(--ink);
    }

    .summary-box {
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--surface-2);
      display: grid;
      gap: 8px;
    }

    .payload-preview {
      min-height: 220px;
      max-height: 420px;
    }

    .quick-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
      min-width: 0;
    }

    .toast {
      position: fixed;
      right: 18px;
      bottom: 18px;
      z-index: 50;
      min-width: 260px;
      max-width: 420px;
      padding: 12px 14px;
      border-radius: var(--radius);
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--ink);
      box-shadow: var(--shadow);
      opacity: 0;
      transform: translateY(10px);
      pointer-events: none;
      transition: opacity 160ms ease, transform 160ms ease;
    }

    .toast.show {
      opacity: 1;
      transform: translateY(0);
    }

    .mini-table {
      width: 100%;
      table-layout: fixed;
      border-collapse: collapse;
      font-size: 13px;
    }

    .mini-table th,
    .mini-table td {
      padding: 9px 8px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      overflow-wrap: anywhere;
    }

    .mini-table th {
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
    }

    .guide {
      display: grid;
      grid-template-columns: repeat(3, minmax(160px, 1fr));
      gap: 10px;
    }

    .guide-item {
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      background: var(--surface-2);
    }

    .guide-item strong {
      display: block;
      margin-bottom: 4px;
    }

    .guide-item span {
      color: var(--muted);
      font-size: 12px;
    }

    .journey-board {
      display: grid;
      grid-template-columns: repeat(4, minmax(170px, 1fr));
      gap: 10px;
      margin-top: 14px;
    }

    .journey-card {
      min-height: 118px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--surface);
      box-shadow: var(--soft-shadow);
      position: relative;
      overflow: hidden;
      animation: enter 280ms ease both;
    }

    .journey-card::before {
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: 4px;
      background: var(--teal);
    }

    .journey-card strong {
      display: block;
      margin-bottom: 6px;
    }

    .journey-card span {
      color: var(--muted);
      font-size: 12px;
      display: block;
    }

    .mobile-only {
      display: none;
    }

    @media (max-width: 1180px) {
      .layout {
        grid-template-columns: 1fr;
      }

      .sidebar {
        position: static;
        max-height: none;
        order: 0;
      }

      .workspace {
        order: -1;
      }

      .hero-strip,
      .form-grid,
      .wide-grid {
        grid-template-columns: 1fr;
      }

      .command-panel {
        grid-template-columns: 1fr;
      }

      .hero-visual {
        min-height: 220px;
        border-left: 0;
        border-top: 1px solid var(--line);
      }

      .hero-visual img {
        object-position: 82% center;
      }

      .journey-board {
        grid-template-columns: repeat(2, minmax(160px, 1fr));
      }
    }

    @media (max-width: 760px) {
      .topbar {
        grid-template-columns: 1fr;
        padding: 12px;
        overflow: hidden;
      }

      .brand {
        align-items: flex-start;
        width: 100%;
      }

      .brand > div {
        max-width: min(280px, calc(100vw - 76px));
      }

      .brand h1,
      .brand .subtle {
        max-width: 100%;
      }

      .brand .subtle {
        display: none;
      }

      .top-actions {
        width: 100%;
        display: grid;
        grid-template-columns: 1fr;
      }

      .top-actions .btn {
        width: 100%;
        min-width: 0;
        padding-inline: 8px;
      }

      .top-actions .btn-primary {
        grid-column: auto;
      }

      .quick-actions .btn {
        flex: 1 1 100%;
      }

      .layout {
        width: 100%;
        max-width: 100%;
        padding: 10px;
        overflow: hidden;
      }

      .panel-header {
        display: grid;
        grid-template-columns: 1fr;
      }

      .panel-header > * {
        min-width: 0;
      }

      .panel-header .pill {
        justify-self: start;
        max-width: 280px;
      }

      .metric-grid,
      .field-grid,
      .checkbox-grid,
      .guide,
      .journey-board {
        grid-template-columns: 1fr;
      }

      .nav-grid,
      .tool-links {
        grid-template-columns: 1fr;
      }

      .screen-head {
        display: grid;
      }
    }
  </style>
</head>
<body>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <div class="mark">WM</div>
        <div>
          <h1>WAMOCON Marketing Console</h1>
          <p class="subtle">Always-on campaign workflow with human approval, evidence, and KPI feedback.</p>
        </div>
      </div>
      <div class="top-actions">
        <select id="uiLanguage" class="language-select" aria-label="UI language" title="UI language">
          <option value="de">Deutsch</option>
          <option value="en">English</option>
        </select>
        <button class="btn btn-secondary" type="button" id="themeToggle" title="Toggle theme">
          <svg class="icon" viewBox="0 0 24 24"><path d="M12 3v2M12 19v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M3 12h2M19 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/><circle cx="12" cy="12" r="4"/></svg>
          Theme
        </button>
        <button class="btn btn-secondary" type="button" data-jump="status">
          <svg class="icon" viewBox="0 0 24 24"><path d="M12 20v-6"/><path d="M6 20V10"/><path d="M18 20V4"/></svg>
          Setup
        </button>
        <button class="btn btn-primary" type="button" id="weeklyPlanTop">
          <svg class="icon" viewBox="0 0 24 24"><path d="M4 5h16v16H4z"/><path d="M16 3v4M8 3v4M4 11h16"/></svg>
          Weekly Plan
        </button>
      </div>
    </header>

    <div class="layout">
      <aside class="sidebar">
        <div class="panel">
          <div class="panel-header">
            <h3>Workflow</h3>
            <span class="pill neutral" id="activeModePill">Intake</span>
          </div>
          <div class="panel-body">
            <div class="step-list">
              <div class="step"><div class="step-number">1</div><div><strong>Brief</strong><span>Campaign, persona, proof, CTA, UTM.</span></div></div>
              <div class="step"><div class="step-number">2</div><div><strong>Draft</strong><span>Agent creates a review draft.</span></div></div>
              <div class="step"><div class="step-number">3</div><div><strong>Approve</strong><span>Human checks brand, privacy, and claims.</span></div></div>
              <div class="step"><div class="step-number">4</div><div><strong>Schedule</strong><span>Draft-only payload, final platform approval required.</span></div></div>
              <div class="step"><div class="step-number">5</div><div><strong>Learn</strong><span>72h, 7d, 14d, and 30d decisions.</span></div></div>
            </div>
          </div>
        </div>

        <div class="panel">
          <div class="panel-body">
            <div class="nav-grid" role="tablist" aria-label="Marketing console sections">
              <button class="nav-tab" data-screen="dashboard" aria-selected="true">
                <svg class="icon" viewBox="0 0 24 24"><path d="M4 13h6V4H4zM14 20h6V4h-6zM4 20h6v-3H4z"/></svg>
                <span class="tab-copy"><strong>Dashboard</strong><span>Overview</span></span>
              </button>
              <button class="nav-tab" data-screen="phases" aria-selected="false">
                <svg class="icon" viewBox="0 0 24 24"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
                <span class="tab-copy"><strong>Phases</strong><span>Readiness</span></span>
              </button>
              <button class="nav-tab" data-screen="trends" aria-selected="false">
                <svg class="icon" viewBox="0 0 24 24"><path d="M3 17l6-6 4 4 8-8"/><path d="M14 7h7v7"/></svg>
                <span class="tab-copy"><strong>Trends</strong><span>Reel studio</span></span>
              </button>
              <button class="nav-tab" data-screen="intake" aria-selected="false">
                <svg class="icon" viewBox="0 0 24 24"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
                <span class="tab-copy"><strong>Intake</strong><span>Create brief</span></span>
              </button>
              <button class="nav-tab" data-screen="approval" aria-selected="false">
                <svg class="icon" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>
                <span class="tab-copy"><strong>Approval</strong><span>Review gate</span></span>
              </button>
              <button class="nav-tab" data-screen="leads" aria-selected="false">
                <svg class="icon" viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-8 0v2"/><circle cx="12" cy="7" r="4"/><path d="M19 8v6"/><path d="M22 11h-6"/></svg>
                <span class="tab-copy"><strong>Leads</strong><span>Score lead</span></span>
              </button>
              <button class="nav-tab" data-screen="routing" aria-selected="false">
                <svg class="icon" viewBox="0 0 24 24"><path d="M4 7h10"/><path d="m10 3 4 4-4 4"/><path d="M20 17H10"/><path d="m14 13-4 4 4 4"/></svg>
                <span class="tab-copy"><strong>Routing</strong><span>Outbox</span></span>
              </button>
              <button class="nav-tab" data-screen="analytics" aria-selected="false">
                <svg class="icon" viewBox="0 0 24 24"><path d="M4 19V5"/><path d="M4 19h16"/><path d="M8 15l3-4 3 2 4-7"/></svg>
                <span class="tab-copy"><strong>Analytics</strong><span>Optimize</span></span>
              </button>
              <button class="nav-tab" data-screen="creative" aria-selected="false">
                <svg class="icon" viewBox="0 0 24 24"><path d="M4 5h16v14H4z"/><path d="m4 15 4-4 4 4 3-3 5 5"/></svg>
                <span class="tab-copy"><strong>Creative</strong><span>ComfyUI brief</span></span>
              </button>
              <button class="nav-tab" data-screen="status" aria-selected="false">
                <svg class="icon" viewBox="0 0 24 24"><path d="M12 20v-6"/><path d="M6 20V10"/><path d="M18 20V4"/></svg>
                <span class="tab-copy"><strong>Status</strong><span>Services</span></span>
              </button>
            </div>
          </div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <h3>Recent Content</h3>
            <button class="btn btn-secondary" type="button" id="refreshRecent" title="Refresh recent content">
              <svg class="icon" viewBox="0 0 24 24"><path d="M21 12a9 9 0 0 1-15.5 6.2"/><path d="M3 12A9 9 0 0 1 18.5 5.8"/><path d="M18 2v4h-4M6 22v-4h4"/></svg>
            </button>
          </div>
          <div class="panel-body">
            <div class="recent-toolbar">
              <input id="recentSearch" placeholder="Search content ID or campaign">
              <button class="btn btn-secondary" type="button" id="clearRecentSearch">Clear</button>
            </div>
            <div class="recent-list" id="recentList"></div>
          </div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <h3>Tools</h3>
          </div>
          <div class="panel-body">
            <div class="tool-links">
              <a href="http://192.168.178.75:15678" target="_blank" rel="noreferrer">n8n <span>open</span></a>
              <a href="http://192.168.178.75:14007" target="_blank" rel="noreferrer">Postiz <span>open</span></a>
              <a href="http://192.168.178.75:14019" target="_blank" rel="noreferrer">Twenty <span>open</span></a>
              <a href="http://192.168.178.75:14020" target="_blank" rel="noreferrer">Mautic <span>open</span></a>
              <a href="http://192.168.178.75:18188" target="_blank" rel="noreferrer">ComfyUI <span>open</span></a>
              <a href="http://192.168.178.75:13030" target="_blank" rel="noreferrer">Grafana <span>open</span></a>
            </div>
          </div>
        </div>
      </aside>

      <main class="workspace">
        <div class="hero-strip">
          <div class="panel command-panel">
            <div class="command-copy">
              <div>
                <div class="hero-kicker">Content workflow</div>
                <h2 class="hero-title" id="screenTitle">Plan better Reels faster</h2>
                <p class="subtle" id="screenDescription">Pick a campaign, find a useful trend, create Reel options, approve the best draft.</p>
              </div>
              <div class="hero-actions">
                <button class="btn btn-primary" type="button" data-jump="trends">Start Trend Scan</button>
                <button class="btn btn-secondary" type="button" data-jump="approval">Review Drafts</button>
              </div>
              <div class="status-row" id="healthPills">
                <span class="pill warn">Checking setup</span>
              </div>
            </div>
            <div class="hero-visual" aria-hidden="true">
              <img src="/static/marketing-workflow-hero.png" alt="">
            </div>
          </div>
          <div class="panel operator-queue" id="metricGrid">
            <div class="queue-item"><small>Setup</small><strong id="metricRequired">...</strong><span class="subtle">sources and model</span></div>
            <div class="queue-item"><small>Content</small><strong id="metricRecent">...</strong><span class="subtle">drafts saved</span></div>
            <div class="queue-item"><small>Needs review</small><strong id="metricReview">...</strong><span class="subtle">waiting for approval</span></div>
            <div class="queue-item"><small>Publishing safety</small><strong id="metricGuard">On</strong><span class="subtle">manual approval</span></div>
          </div>
        </div>

        <section class="screen active" id="screen-dashboard" data-title="Dashboard" data-description="Pick a campaign, find a useful trend, create Reel options, approve the best draft.">
          <div class="screen-head">
            <div>
              <h2>Today</h2>
              <p>Choose one next step. The system keeps posts as drafts until you approve them.</p>
            </div>
            <div class="quick-actions">
              <button class="btn btn-primary" type="button" data-jump="trends">Trend Scan</button>
              <button class="btn btn-primary" type="button" data-jump="intake">New Brief</button>
              <button class="btn btn-secondary" type="button" data-jump="approval">Approve Draft</button>
              <button class="btn btn-secondary" type="button" data-jump="leads">Add Lead</button>
              <button class="btn btn-secondary" type="button" data-jump="routing">Route</button>
              <button class="btn btn-secondary" type="button" data-jump="analytics">Review KPIs</button>
            </div>
          </div>
          <div class="journey-board">
            <button class="journey-card" type="button" data-jump="trends"><strong>1. Find Reel Trends</strong><span>Scan current sources and pick a campaign-ready idea.</span></button>
            <button class="journey-card" type="button" data-jump="trends"><strong>2. Create Reel Options</strong><span>Generate hooks, shot lists, captions, and CTA ideas.</span></button>
            <button class="journey-card" type="button" data-jump="approval"><strong>3. Review Draft</strong><span>Check proof, privacy, brand fit, and AI disclosure.</span></button>
            <button class="journey-card" type="button" data-jump="routing"><strong>4. Send To Scheduler</strong><span>Prepare a draft-only handoff after approval.</span></button>
          </div>
          <div class="panel" style="margin-top:14px">
            <div class="panel-header">
              <h3>Recent States</h3>
              <button class="btn btn-secondary" type="button" id="copyRecentSummary">Copy Summary</button>
            </div>
            <div class="panel-body">
              <table class="mini-table">
                <thead><tr><th>Content</th><th>Campaign</th><th>Status</th><th>Next</th></tr></thead>
                <tbody id="recentTableBody"><tr><td colspan="4">Loading...</td></tr></tbody>
              </table>
            </div>
          </div>
        </section>

        <section class="screen" id="screen-trends" data-title="Trend Studio" data-description="Find current ideas, turn them into Reel drafts, and send the best one to review.">
          <div class="screen-head">
            <div>
              <h2>Trend Studio</h2>
              <p>Scan current sources, choose a trend, then create Reel ideas for the selected campaign.</p>
            </div>
            <div class="quick-actions">
              <button class="btn btn-primary" type="button" id="runTrendScan">Find Trends</button>
              <button class="btn btn-secondary" type="button" id="refreshTrendRuns">Saved Scans</button>
            </div>
          </div>
          <div class="wide-grid">
            <div class="panel">
              <div class="panel-body">
                <h3>What should we scan?</h3>
                <div class="field-grid">
                  <div><label for="trendLookback">Recent days</label><input id="trendLookback" type="number" min="1" max="30" value="10"></div>
                  <div><label for="trendLimit">Ideas per campaign</label><input id="trendLimit" type="number" min="1" max="8" value="4"></div>
                  <div><label for="trendVariantCount">Reel options</label><input id="trendVariantCount" type="number" min="1" max="6" value="4"></div>
                </div>
                <div class="checkbox-grid" id="trendPlatforms">
                  <label><input type="checkbox" value="instagram" checked> Instagram Reels</label>
                  <label><input type="checkbox" value="tiktok" checked> TikTok</label>
                  <label><input type="checkbox" value="reddit" checked> Reddit</label>
                  <label><input type="checkbox" value="forums" checked> Forums</label>
                  <label><input type="checkbox" value="web" checked> Web / Google</label>
                </div>
                <label for="trendUserPrompt">Direction for the Reel</label>
                <textarea id="trendUserPrompt" placeholder="Beispiel: mehr Q&A, visueller, direkter fuer Instagram."></textarea>
              </div>
            </div>
            <div class="panel result-panel">
              <div class="result-toolbar">
                <h3>Scan Result</h3>
                <button class="btn btn-secondary" type="button" data-copy="trendRunResult">Copy</button>
              </div>
              <div class="summary-box" id="trendRunSummary"><span class="pill neutral">No scan yet</span></div>
              <pre id="trendRunResult">Click Find Trends to get campaign ideas.</pre>
            </div>
          </div>
          <div class="wide-grid" style="margin-top:14px">
            <div class="panel">
              <div class="panel-header"><h3>Campaign Ideas</h3><span class="pill neutral" id="trendSelectedPill">Select idea</span></div>
              <div class="panel-body">
                <div class="recent-list" id="trendCampaigns"><span class="pill neutral">No ideas loaded</span></div>
              </div>
            </div>
            <div class="panel result-panel">
              <div class="result-toolbar">
                <h3>Reel Ideas</h3>
                <div class="quick-actions">
                  <button class="btn btn-secondary" type="button" id="generateTrendConcept">Create Ideas</button>
                  <button class="btn btn-secondary" type="button" id="approveTrendConcept">Send First To Review</button>
                  <button class="btn btn-secondary" type="button" data-copy="trendConceptResult">Copy</button>
                </div>
              </div>
              <div class="summary-box" id="trendConceptSummary"><span class="pill neutral">Select an idea first</span></div>
              <pre id="trendConceptResult">Choose a campaign idea, then create Reel options.</pre>
            </div>
          </div>
        </section>

        <section class="screen" id="screen-phases" data-title="Phase Readiness" data-description="See which implementation phases are finished, partial, or blocked before running campaigns.">
          <div class="screen-head">
            <div>
              <h2>Phase Readiness</h2>
              <p>This is the morning checklist for the marketing machine: core flow, model plane, n8n rhythm, publishing, CRM, creative, and production hardening.</p>
            </div>
            <div class="quick-actions">
              <button class="btn btn-primary" type="button" id="refreshPhases">Refresh Phases</button>
            </div>
          </div>
          <div class="wide-grid">
            <div class="panel">
              <div class="panel-header"><h3>Implementation Phases</h3></div>
              <div class="panel-body">
                <div class="status-row" id="phaseSummary"><span class="pill neutral">Loading</span></div>
                <table class="mini-table" style="margin-top:12px">
                  <thead><tr><th>Phase</th><th>Status</th><th>Next action</th></tr></thead>
                  <tbody id="phaseTableBody"><tr><td colspan="3">Loading...</td></tr></tbody>
                </table>
              </div>
            </div>
            <div class="panel result-panel">
              <div class="result-toolbar">
                <h3>Raw Phase Report</h3>
                <button class="btn btn-secondary" type="button" data-copy="phaseResult">Copy</button>
              </div>
              <pre id="phaseResult">Loading...</pre>
            </div>
          </div>
        </section>

        <section class="screen" id="screen-intake" data-title="Manual Content Intake" data-description="Create a campaign brief with proof, CTA, UTM tracking, and a test hypothesis.">
          <div class="screen-head">
            <div>
              <h2>Manual Content Intake</h2>
              <p>Use this when someone has a campaign idea, proof asset, offer, customer-safe story, or post request.</p>
            </div>
            <div class="quick-actions">
              <button class="btn btn-secondary" type="button" id="copyPayloadPreview">Copy Payload</button>
              <button class="btn btn-secondary" type="button" id="resetIntake">Reset</button>
            </div>
          </div>
          <form id="intakeForm" class="form-grid" autocomplete="off">
            <div class="stack">
              <div class="panel">
                <div class="panel-body">
                  <div class="section-title"><span class="badge">1</span><h3>Campaign Brief</h3></div>
                  <label for="preset">Preset</label>
                  <select id="preset">
                    <option value="k1">K1 QA Risk Audit</option>
                    <option value="k2">K2 Private AI Discovery</option>
                    <option value="k3">K3 LFA Azubi Reel</option>
                    <option value="k4">K4 Mitarbeiter Reel</option>
                    <option value="k5">K5 App Modernization</option>
                    <option value="custom">Custom</option>
                  </select>
                  <label for="contentId">Content ID</label>
                  <div class="input-with-action">
                    <input id="contentId" name="id" required>
                    <button class="btn btn-secondary" type="button" id="regenId">Regenerate</button>
                  </div>
                  <label for="campaign">Campaign</label>
                  <input id="campaign" name="campaign" required>
                  <label for="persona">Persona</label>
                  <input id="persona" name="persona" required>
                  <div class="field-grid">
                    <div>
                      <label for="language">AI draft language</label>
                      <select id="language" name="language">
                        <option value="de-DE">Deutsch (Deutschland)</option>
                        <option value="en-US">English (US)</option>
                      </select>
                    </div>
                    <div>
                      <label for="channel">Channel</label>
                      <select id="channel" name="channel">
                        <option>LinkedIn</option>
                        <option>Instagram</option>
                        <option>Email</option>
                        <option>Landing Page</option>
                      </select>
                    </div>
                    <div>
                      <label for="format">Format</label>
                      <select id="format" name="format">
                        <option value="expert_post">Expert post</option>
                        <option value="carousel">Carousel</option>
                        <option value="reel">Reel</option>
                        <option value="video_script">Video script</option>
                        <option value="app_demo_post">App demo post</option>
                        <option value="email">Email</option>
                      </select>
                    </div>
                    <div>
                      <label for="testVariable">Test variable</label>
                      <select id="testVariable" name="test_variable">
                        <option value="hook">Hook</option>
                        <option value="offer">Offer</option>
                        <option value="format">Format</option>
                        <option value="persona">Persona</option>
                        <option value="cta">CTA</option>
                        <option value="landing_page">Landing page</option>
                      </select>
                    </div>
                  </div>
                </div>
              </div>

              <div class="panel">
                <div class="panel-body">
                  <div class="section-title"><span class="badge">2</span><h3>Proof And Offer</h3></div>
                  <label for="objective">Objective</label>
                  <textarea id="objective" name="objective" required></textarea>
                  <label for="cta">CTA</label>
                  <input id="cta" name="cta" required>
                  <label for="proofSources">Proof sources</label>
                  <textarea id="proofSources" name="proof_sources" required></textarea>
                  <label for="hypothesis">Hypothesis</label>
                  <textarea id="hypothesis" name="hypothesis" required></textarea>
                  <label for="hashtags">Hashtags</label>
                  <input id="hashtags" name="hashtags" placeholder="3 to 5 for Instagram">
                </div>
              </div>

              <div class="panel">
                <div class="panel-body">
                  <div class="section-title"><span class="badge">3</span><h3>Tracking</h3></div>
                  <div class="field-grid">
                    <div>
                      <label for="utmSource">UTM source</label>
                      <input id="utmSource" value="linkedin" required>
                    </div>
                    <div>
                      <label for="utmMedium">UTM medium</label>
                      <input id="utmMedium" value="organic" required>
                    </div>
                    <div>
                      <label for="utmCampaign">UTM campaign</label>
                      <input id="utmCampaign" required>
                    </div>
                  </div>
                  <div class="quick-actions">
                    <button class="btn btn-primary" type="submit">Create Draft</button>
                    <span class="pill warn">No publishing from intake</span>
                  </div>
                </div>
              </div>
            </div>

            <div class="stack">
              <div class="panel">
                <div class="panel-body quality">
                  <div class="section-title"><span class="badge">Q</span><h3>Readiness Score</h3></div>
                  <div class="quality-meter" aria-label="Brief readiness"><span id="qualityBar"></span></div>
                  <div class="status-row"><span class="pill neutral" id="qualityScore">0%</span></div>
                  <div class="checklist" id="qualityChecks"></div>
                </div>
              </div>
              <div class="panel result-panel">
                <div class="result-toolbar">
                  <h3>Live Payload Preview</h3>
                  <span class="pill neutral">JSON</span>
                </div>
                <pre class="payload-preview" id="payloadPreview">Loading...</pre>
              </div>
              <div class="panel result-panel">
                <div class="result-toolbar">
                  <h3>Intake Result</h3>
                  <button class="btn btn-secondary" type="button" data-copy="intakeResult">Copy</button>
                </div>
                <div class="summary-box" id="intakeSummary"><span class="pill neutral">Waiting for draft</span></div>
                <pre id="intakeResult">Submit a campaign brief to see the draft state.</pre>
              </div>
              <div class="panel result-panel">
                <div class="result-toolbar">
                  <h3>Created Post Preview</h3>
                  <button class="btn btn-secondary" type="button" data-copy="postPreview">Copy Post</button>
                </div>
                <pre id="postPreview">Create a draft to see the public post text here.</pre>
              </div>
            </div>
          </form>
        </section>

        <section class="screen" id="screen-approval" data-title="Human Approval" data-description="Approve only after checking the draft, proof source, privacy, consent, and AI disclosure.">
          <div class="screen-head">
            <div>
              <h2>Human Approval</h2>
              <p>This gate keeps public publishing separate from AI drafting. Scheduler output remains draft-only.</p>
            </div>
            <div class="quick-actions">
              <button class="btn btn-secondary" type="button" id="loadApprovalState">Load State</button>
              <button class="btn btn-danger" type="button" id="requestRevision">Request Revision</button>
            </div>
          </div>
          <form id="approvalForm" class="wide-grid" autocomplete="off">
            <div class="panel">
              <div class="panel-body">
                <h3>Review Decision</h3>
                <label for="approvalContentId">Content ID</label>
                <input id="approvalContentId" name="content_id" required>
                <label for="reviewer">Reviewer</label>
                <input id="reviewer" value="wamocon-reviewer" required>
                <div class="field-grid">
                  <div>
                    <label for="decision">Decision</label>
                    <select id="decision">
                      <option value="approved">Approved</option>
                      <option value="minor_revision">Minor revision</option>
                      <option value="major_revision">Major revision</option>
                      <option value="rejected">Rejected</option>
                    </select>
                  </div>
                  <div>
                    <label for="brandScore">Brand score</label>
                    <input id="brandScore" type="number" min="0" max="100" value="95" required>
                  </div>
                  <div>
                    <label>Publishability</label>
                    <div class="status-row"><span class="pill warn" id="publishabilityPill">Needs checks</span></div>
                  </div>
                </div>
                <div class="checkbox-grid">
                  <label><input id="factCheck" type="checkbox" checked> Fact check passed</label>
                  <label><input id="privacyCheck" type="checkbox" checked> Privacy check passed</label>
                  <label><input id="disclosureCheck" type="checkbox" checked> AI disclosure checked</label>
                </div>
                <label for="approvalNotes">Notes</label>
                <textarea id="approvalNotes">Menschliche Prüfung abgeschlossen. Finale Plattformfreigabe bleibt erforderlich.</textarea>
                <div class="quick-actions">
                  <button class="btn btn-primary" type="submit">Apply Approval</button>
                  <span class="pill warn">Final Postiz approval still required</span>
                </div>
              </div>
            </div>
            <div class="panel result-panel">
              <div class="result-toolbar">
                <h3>Approval Result</h3>
                <button class="btn btn-secondary" type="button" data-copy="approvalResult">Copy</button>
              </div>
              <div class="summary-box" id="approvalSummary"><span class="pill neutral">Waiting for approval</span></div>
              <pre id="approvalResult">Approve only after checking proof, consent, brand fit, and claims.</pre>
              <div class="result-toolbar">
                <h3>Scheduler Draft Preview</h3>
                <button class="btn btn-secondary" type="button" data-copy="schedulerPreview">Copy Draft</button>
              </div>
              <pre id="schedulerPreview">Approved content will show the draft-only scheduler copy here.</pre>
            </div>
          </form>
        </section>

        <section class="screen" id="screen-leads" data-title="Lead Intake" data-description="Capture a real response, check consent, score the lead, and prepare CRM/marketing automation payloads.">
          <div class="screen-head">
            <div>
              <h2>Lead Intake</h2>
              <p>Use this when a post, landing page, email, or direct message creates a business enquiry.</p>
            </div>
            <div class="quick-actions">
              <button class="btn btn-secondary" type="button" id="loadLeadExample">Load Example</button>
              <button class="btn btn-secondary" type="button" id="refreshLeads">Refresh Leads</button>
            </div>
          </div>
          <form id="leadForm" class="wide-grid" autocomplete="off">
            <div class="panel">
              <div class="panel-body">
                <h3>Lead Details</h3>
                <label for="leadId">Lead ID</label>
                <input id="leadId" required>
                <label for="leadSourceContentId">Source content ID</label>
                <input id="leadSourceContentId" required>
                <div class="field-grid">
                  <div><label for="leadCampaign">Campaign</label><input id="leadCampaign" value="K1 QA Consulting" required></div>
                  <div><label for="leadOffer">Offer</label><input id="leadOffer" value="QA-Risikoaudit" required></div>
                  <div><label for="leadPersona">Persona</label><input id="leadPersona" value="IT-Leiter Thomas" required></div>
                </div>
                <div class="field-grid">
                  <div><label for="leadContactName">Contact name</label><input id="leadContactName" value="Max Mustermann"></div>
                  <div><label for="leadCompany">Company</label><input id="leadCompany" value="Muster GmbH"></div>
                  <div><label for="leadEmail">Email</label><input id="leadEmail" type="email" value="it-leitung@muster-gmbh.de"></div>
                </div>
                <label for="leadPhone">Phone</label>
                <input id="leadPhone" placeholder="+49 ...">
                <label for="leadMessage">Message / intent</label>
                <textarea id="leadMessage">Wir möchten einen QA-Risikoaudit Termin anfragen.</textarea>
                <div class="checkbox-grid">
                  <label><input id="leadConsent" type="checkbox" checked> Consent for follow-up is documented</label>
                </div>
                <h3 style="margin-top:14px">Attribution</h3>
                <div class="field-grid">
                  <div><label for="leadUtmSource">UTM source</label><input id="leadUtmSource" value="linkedin"></div>
                  <div><label for="leadUtmMedium">UTM medium</label><input id="leadUtmMedium" value="organic"></div>
                  <div><label for="leadUtmCampaign">UTM campaign</label><input id="leadUtmCampaign" value="k1_qa_risk_audit"></div>
                </div>
                <div class="quick-actions">
                  <button class="btn btn-primary" type="submit">Score Lead</button>
                  <span class="pill warn">No auto CRM write without credentials</span>
                </div>
              </div>
            </div>
            <div class="stack">
              <div class="panel result-panel">
                <div class="result-toolbar">
                  <h3>Lead Result</h3>
                  <button class="btn btn-secondary" type="button" data-copy="leadResult">Copy</button>
                </div>
                <div class="summary-box" id="leadSummary"><span class="pill neutral">Waiting for lead</span></div>
                <pre id="leadResult">Submit a lead to see score, next action, and CRM/Mautic payloads.</pre>
              </div>
              <div class="panel">
                <div class="panel-header"><h3>Recent Leads</h3></div>
                <div class="panel-body">
                  <table class="mini-table">
                    <thead><tr><th>Lead</th><th>Campaign</th><th>Company</th><th>Next</th></tr></thead>
                    <tbody id="leadTableBody"><tr><td colspan="4">No leads loaded</td></tr></tbody>
                  </table>
                </div>
              </div>
            </div>
          </form>
        </section>

        <section class="screen" id="screen-routing" data-title="Routing Outbox" data-description="Prepare approved drafts and qualified leads for external tools with dry-run and audit trail first.">
          <div class="screen-head">
            <div>
              <h2>Routing Outbox</h2>
              <p>Use this after approval or lead scoring. Dry-run is the default; real external writes need explicit server credentials and write enablement.</p>
            </div>
            <div class="quick-actions">
              <button class="btn btn-secondary" type="button" id="refreshOutbox">Refresh Outbox</button>
            </div>
          </div>
          <div class="wide-grid">
            <div class="stack">
              <div class="panel">
                <div class="panel-body">
                  <h3>Postiz Draft Route</h3>
                  <label for="routeContentId">Content ID</label>
                  <input id="routeContentId" placeholder="approved content ID">
                  <label for="routeSchedulerTarget">Target</label>
                  <select id="routeSchedulerTarget">
                    <option value="postiz">Postiz draft</option>
                  </select>
                  <div class="checkbox-grid">
                    <label><input id="routeSchedulerDryRun" type="checkbox" checked> Dry-run only</label>
                  </div>
                  <div class="quick-actions">
                    <button class="btn btn-primary" type="button" id="routeSchedulerDraft">Prepare Postiz Draft</button>
                  </div>
                </div>
              </div>
              <div class="panel">
                <div class="panel-body">
                  <h3>Lead Route</h3>
                  <label for="routeLeadId">Lead ID</label>
                  <input id="routeLeadId" placeholder="qualified lead ID">
                  <label for="routeLeadTarget">Target</label>
                  <select id="routeLeadTarget">
                    <option value="twenty">Twenty CRM</option>
                    <option value="mautic">Mautic nurture</option>
                  </select>
                  <div class="checkbox-grid">
                    <label><input id="routeLeadDryRun" type="checkbox" checked> Dry-run only</label>
                  </div>
                  <div class="quick-actions">
                    <button class="btn btn-primary" type="button" id="routeLead">Prepare Lead Route</button>
                  </div>
                </div>
              </div>
            </div>
            <div class="stack">
              <div class="panel result-panel">
                <div class="result-toolbar">
                  <h3>Route Result</h3>
                  <button class="btn btn-secondary" type="button" data-copy="routeResult">Copy</button>
                </div>
                <div class="summary-box" id="routeSummary"><span class="pill neutral">Waiting for route</span></div>
                <pre id="routeResult">Prepare a Postiz draft or lead route to see the outbox record.</pre>
              </div>
              <div class="panel">
                <div class="panel-header"><h3>Recent Outbox</h3></div>
                <div class="panel-body">
                  <table class="mini-table">
                    <thead><tr><th>Route</th><th>Target</th><th>Status</th><th>Source</th></tr></thead>
                    <tbody id="outboxTableBody"><tr><td colspan="4">No outbox records loaded</td></tr></tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section class="screen" id="screen-analytics" data-title="Optimization Review" data-description="Enter performance signals and get a clear decision: scale, iterate, fix landing page, fix audience/offer, or stop.">
          <div class="screen-head">
            <div>
              <h2>Optimization Review</h2>
              <p>Do not wait 30 days. Start reading useful signal after 72 hours, then review at 7, 14, and 30 days.</p>
            </div>
            <div class="quick-actions">
              <button class="btn btn-secondary" type="button" id="loadWeakSignal">Load Weak Signal</button>
              <button class="btn btn-secondary" type="button" id="loadScaleSignal">Load Scale Signal</button>
            </div>
          </div>
          <form id="analyticsForm" class="wide-grid" autocomplete="off">
            <div class="panel">
              <div class="panel-body">
                <h3>KPI Input</h3>
                <label for="analyticsContentId">Content ID</label>
                <input id="analyticsContentId" required>
                <label for="reviewWindow">Review window</label>
                <select id="reviewWindow">
                  <option value="72h">72h</option>
                  <option value="7d">7d</option>
                  <option value="14d">14d</option>
                  <option value="30d">30d</option>
                </select>
                <div class="field-grid">
                  <div><label for="impressions">Impressions</label><input id="impressions" type="number" min="0" value="0"></div>
                  <div><label for="saves">Saves</label><input id="saves" type="number" min="0" value="0"></div>
                  <div><label for="shares">Shares</label><input id="shares" type="number" min="0" value="0"></div>
                </div>
                <div class="field-grid">
                  <div><label for="buyerComments">Buyer comments</label><input id="buyerComments" type="number" min="0" value="0"></div>
                  <div><label for="profileVisits">Profile visits</label><input id="profileVisits" type="number" min="0" value="0"></div>
                  <div><label for="clicks">Clicks</label><input id="clicks" type="number" min="0" value="0"></div>
                </div>
                <div class="field-grid">
                  <div><label for="leads">Leads</label><input id="leads" type="number" min="0" value="0"></div>
                  <div><label for="qualifiedLeads">Qualified leads</label><input id="qualifiedLeads" type="number" min="0" value="0"></div>
                  <div><label for="bookedCalls">Booked calls</label><input id="bookedCalls" type="number" min="0" value="0"></div>
                </div>
                <div class="field-grid">
                  <div><label for="landingVisits">Landing visits</label><input id="landingVisits" type="number" min="0" value="0"></div>
                  <div><label for="landingConversions">Landing conversions</label><input id="landingConversions" type="number" min="0" value="0"></div>
                  <div><label for="pipelineValue">Pipeline EUR</label><input id="pipelineValue" type="number" min="0" value="0"></div>
                </div>
                <div class="quick-actions">
                  <button class="btn btn-primary" type="submit">Evaluate</button>
                </div>
              </div>
            </div>
            <div class="panel result-panel">
              <div class="result-toolbar">
                <h3>Decision</h3>
                <button class="btn btn-secondary" type="button" data-copy="analyticsResult">Copy</button>
              </div>
              <div class="summary-box" id="analyticsSummary"><span class="pill neutral">Waiting for KPI input</span></div>
              <pre id="analyticsResult">Enter metrics after 72h, 7d, 14d, or 30d.</pre>
            </div>
          </form>
        </section>

        <section class="screen" id="screen-creative" data-title="Creative Brief" data-description="Create a ComfyUI-ready visual brief without auto-submitting generation jobs.">
          <div class="screen-head">
            <div>
              <h2>Creative Brief</h2>
              <p>Use approved proof assets only. Human visual approval is required before public use.</p>
            </div>
          </div>
          <form id="creativeForm" class="wide-grid" autocomplete="off">
            <div class="panel">
              <div class="panel-body">
                <h3>Visual Request</h3>
                <label for="creativeCampaign">Campaign</label>
                <input id="creativeCampaign" value="K5 App Development">
                <div class="field-grid">
                  <div>
                    <label for="creativeChannel">Channel</label>
                    <select id="creativeChannel">
                      <option>LinkedIn</option>
                      <option>Instagram</option>
                      <option>Landing Page</option>
                    </select>
                  </div>
                  <div>
                    <label for="creativeFormat">Format</label>
                    <input id="creativeFormat" value="app_demo_thumbnail">
                  </div>
                  <div>
                    <label for="outputSize">Output size</label>
                    <select id="outputSize">
                      <option>1080x1350</option>
                      <option>1080x1080</option>
                      <option>1920x1080</option>
                    </select>
                  </div>
                </div>
                <label for="headline">Headline</label>
                <input id="headline" value="Belege statt Versprechen">
                <label for="proofAssetRefs">Proof asset refs</label>
                <textarea id="proofAssetRefs" placeholder="approved screenshot, consent ref, app proof"></textarea>
                <div class="quick-actions"><button class="btn btn-primary" type="submit">Create Creative Brief</button></div>
              </div>
            </div>
            <div class="panel result-panel">
              <div class="result-toolbar">
                <h3>Creative Result</h3>
                <button class="btn btn-secondary" type="button" data-copy="creativeResult">Copy</button>
              </div>
              <div class="summary-box"><span class="pill warn">No automatic ComfyUI job submission</span></div>
              <pre id="creativeResult">Creative briefs require human visual approval before use.</pre>
            </div>
          </form>
        </section>

        <section class="screen" id="screen-status" data-title="System Status" data-description="Required services must be green. Kimi is optional backup only.">
          <div class="screen-head">
            <div>
              <h2>System Status</h2>
              <p>Check n8n, ComfyUI, Ollama/Qwen, growth tools, and optional Kimi provider.</p>
            </div>
            <div class="quick-actions">
              <button class="btn btn-primary" type="button" id="refreshStatus">Refresh Status</button>
            </div>
          </div>
          <div class="wide-grid">
            <div class="panel">
              <div class="panel-header"><h3>Service Summary</h3></div>
              <div class="panel-body" id="serviceSummary"></div>
            </div>
            <div class="panel result-panel">
              <div class="result-toolbar">
                <h3>Raw Status</h3>
                <button class="btn btn-secondary" type="button" data-copy="statusResult">Copy</button>
              </div>
              <pre id="statusResult">Loading...</pre>
            </div>
          </div>
        </section>
      </main>
    </div>
  </div>

  <div class="toast" id="toast">Ready</div>

  <script>
    const presets = {
      k1: {
        idPrefix: "k1-qa-risk-audit",
        campaign: "K1 QA Consulting",
        persona: "IT-Leiter Thomas",
        channel: "LinkedIn",
        format: "expert_post",
        language: "de-DE",
        objective: "QA-Risikoaudit mit senioriger Testexpertise und belegbaren Prüfpunkten anbieten.",
        cta: "QA-Risikoaudit anfragen",
        proof_sources: "Kampagnen/kampagne_1_consulting_qa.json",
        hypothesis: "Ein nachweisbasierter QA-Beitrag erzeugt qualifizierte Anfragen von IT-Leitern.",
        test_variable: "offer",
        utm_source: "linkedin",
        utm_medium: "organic",
        utm_campaign: "k1_qa_risk_audit"
      },
      k2: {
        idPrefix: "k2-private-ai-discovery",
        campaign: "K2 Sokrates Private AI",
        persona: "Geschäftsführer Markus",
        channel: "LinkedIn",
        format: "carousel",
        language: "de-DE",
        objective: "Private-KI-Potenzialanalyse erklären, ohne Unternehmenswissen in öffentliche KI-Systeme zu geben.",
        cta: "Private-KI-Erstgespräch anfragen",
        proof_sources: "Kampagnen/kampagne_2_ki_sokrates.json",
        hypothesis: "Datensouveräne KI-Positionierung erzeugt qualifizierte Gespräche mit Geschäftsführern.",
        test_variable: "positioning",
        utm_source: "linkedin",
        utm_medium: "organic",
        utm_campaign: "k2_private_ai_discovery"
      },
      k3: {
        idPrefix: "k3-lfa-azubi",
        campaign: "K3 LFA Azubi",
        persona: "Azubi, Ausbilder oder HR-Verantwortliche",
        channel: "Instagram",
        format: "reel",
        language: "de-DE",
        objective: "LFA und moderne Fachinformatiker-Ausbildung mit authentischen Einblicken positionieren.",
        cta: "LFA-Demo oder Ausbildungsplatz-Info anfragen",
        proof_sources: "Kampagnen/kampagne_3_lfa_azubis.json",
        hypothesis: "Authentische LFA-Reels erzeugen Saves, Profilbesuche und qualifizierte Ausbildungs-/B2B-Anfragen.",
        test_variable: "format",
        utm_source: "instagram",
        utm_medium: "organic_reel",
        utm_campaign: "k3_lfa_azubi"
      },
      k4: {
        idPrefix: "k4-employee-brand",
        campaign: "K4 Mitarbeiter",
        persona: "Bewerber und B2B-Entscheider",
        channel: "Instagram",
        format: "reel",
        language: "de-DE",
        objective: "WAMOCON-Team, Kultur und Consulting-Vertrauen durch menschliche Einblicke sichtbar machen.",
        cta: "Team kennenlernen",
        proof_sources: "Kampagnen/kampagne_4_mitarbeiter.json",
        hypothesis: "Mitarbeiternahe Reels bauen Vertrauen fuer Recruiting und Consulting-Anfragen auf.",
        test_variable: "story_angle",
        utm_source: "instagram",
        utm_medium: "organic_reel",
        utm_campaign: "k4_employee_brand"
      },
      k5: {
        idPrefix: "k5-app-modernization",
        campaign: "K5 App Development",
        persona: "IT-Leiter Thomas",
        channel: "LinkedIn",
        format: "app_demo_post",
        language: "de-DE",
        objective: "App-Portfolio als Nachweis für einen App-Modernisierungscheck nutzen.",
        cta: "App-Modernisierungscheck anfragen",
        proof_sources: "Kampagnen/kampagne_5_app_entwicklung.json",
        hypothesis: "Konkrete App-Beispiele erzeugen bessere B2B-Anfragen als generische Softwaretexte.",
        test_variable: "proof_asset",
        utm_source: "linkedin",
        utm_medium: "organic",
        utm_campaign: "k5_app_modernization"
      }
    };

    let recentItems = [];
    let recentLeads = [];
    let recentOutbox = [];
    let phaseItems = [];
    let activeTrendRun = null;
    let activeTrendSelection = null;
    let activeTrendConcept = null;
    let lastResult = {};
    let currentUiLanguage = "de";
    const $ = (id) => document.getElementById(id);
    const splitList = (value) => value.split(/[\\n,]+/).map((item) => item.trim()).filter(Boolean);
    const stamp = () => new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "");
    const intValue = (id) => Number.parseInt($(id).value || "0", 10) || 0;
    const floatValue = (id) => Number.parseFloat($(id).value || "0") || 0;

    const i18nTextPairs = [
      ["WAMOCON Marketing Console", "WAMOCON Marketing-Konsole"],
      ["Always-on campaign workflow with human approval, evidence, and KPI feedback.", "Immer aktiver Kampagnenablauf mit menschlicher Freigabe, Belegen und KPI-Lernen."],
      ["Theme", "Design"],
      ["API Docs", "API-Doku"],
      ["Weekly Plan", "Wochenplan"],
      ["Workflow", "Ablauf"],
      ["Intake", "Eingabe"],
      ["Brief", "Briefing"],
      ["Campaign, persona, proof, CTA, UTM.", "Kampagne, Persona, Beleg, CTA, UTM."],
      ["Draft", "Entwurf"],
      ["Agent creates a review draft.", "Der Agent erstellt einen Prüfentwurf."],
      ["Approve", "Freigeben"],
      ["Human checks brand, privacy, and claims.", "Ein Mensch prüft Marke, Datenschutz und Aussagen."],
      ["Schedule", "Planen"],
      ["Draft-only payload, final platform approval required.", "Nur Entwurfspayload, finale Plattformfreigabe erforderlich."],
      ["Learn", "Lernen"],
      ["72h, 7d, 14d, and 30d decisions.", "Entscheidungen nach 72h, 7d, 14d und 30d."],
      ["Dashboard", "Übersicht"],
      ["Overview", "Überblick"],
      ["Phases", "Phasen"],
      ["Readiness", "Bereitschaft"],
      ["Trends", "Trends"],
      ["Reel studio", "Reel-Studio"],
      ["Create brief", "Briefing erstellen"],
      ["Approval", "Freigabe"],
      ["Review gate", "Prüfschritt"],
      ["Leads", "Leads"],
      ["Score lead", "Lead bewerten"],
      ["Score Lead", "Lead bewerten"],
      ["Routing", "Weiterleitung"],
      ["Outbox", "Ausgang"],
      ["Analytics", "Analyse"],
      ["Optimize", "Optimieren"],
      ["Creative", "Kreativ"],
      ["ComfyUI brief", "ComfyUI-Briefing"],
      ["Status", "Status"],
      ["Services", "Dienste"],
      ["Recent Content", "Aktuelle Inhalte"],
      ["Clear", "Leeren"],
      ["Tools", "Werkzeuge"],
      ["open", "öffnen"],
      ["Required services", "Pflichtdienste"],
      ["n8n, ComfyUI, local model", "n8n, ComfyUI, lokales Modell"],
      ["Recent items", "Aktuelle Einträge"],
      ["stored content states", "gespeicherte Content-Stände"],
      ["Review queue", "Prüfwarteschlange"],
      ["human review needed", "menschliche Prüfung nötig"],
      ["Guardrail", "Schutzregel"],
      ["On", "An"],
      ["no auto-publish", "kein Auto-Publishing"],
      ["Today", "Heute"],
      ["Content workflow", "Content-Ablauf"],
      ["Plan better Reels faster", "Reels schneller planen"],
      ["Pick a campaign, find a useful trend, create Reel options, approve the best draft.", "Kampagne waehlen, Trend finden, Reel-Optionen erstellen und den besten Entwurf freigeben."],
      ["Start Trend Scan", "Trend-Scan starten"],
      ["Review Drafts", "Entwuerfe pruefen"],
      ["Checking setup", "Setup wird geprueft"],
      ["sources and model", "Quellen und Modell"],
      ["drafts saved", "Entwuerfe gespeichert"],
      ["Needs review", "Zu pruefen"],
      ["waiting for approval", "wartet auf Freigabe"],
      ["Publishing safety", "Publishing-Schutz"],
      ["manual approval", "manuelle Freigabe"],
      ["Choose one next step. The system keeps posts as drafts until you approve them.", "Waehle den naechsten Schritt. Beitraege bleiben Entwuerfe, bis du sie freigibst."],
      ["Trend Scan", "Trend-Scan"],
      ["Find Reel Trends", "Reel-Trends finden"],
      ["Create Reel Options", "Reel-Optionen erstellen"],
      ["Review Draft", "Entwurf pruefen"],
      ["Send To Scheduler", "An Scheduler geben"],
      ["1. Find Reel Trends", "1. Reel-Trends finden"],
      ["2. Create Reel Options", "2. Reel-Optionen erstellen"],
      ["3. Review Draft", "3. Entwurf pruefen"],
      ["4. Send To Scheduler", "4. An Scheduler geben"],
      ["Scan current sources and pick a campaign-ready idea.", "Aktuelle Quellen scannen und eine passende Kampagnenidee waehlen."],
      ["Generate hooks, shot lists, captions, and CTA ideas.", "Hooks, Shotlists, Captions und CTA-Ideen erzeugen."],
      ["Check proof, privacy, brand fit, and AI disclosure.", "Belege, Datenschutz, Markenfit und AI-Kennzeichnung pruefen."],
      ["Prepare a draft-only handoff after approval.", "Nach Freigabe einen reinen Entwurf vorbereiten."],
      ["Start with intake, then approval, then analytics. The system stays draft-only until a human publishes in the platform.", "Beginne mit Eingabe, dann Freigabe, dann Analyse. Das System bleibt im Entwurfsmodus, bis ein Mensch auf der Plattform veröffentlicht."],
      ["New Brief", "Neues Briefing"],
      ["Approve Draft", "Entwurf freigeben"],
      ["Add Lead", "Lead erfassen"],
      ["Route", "Weiterleiten"],
      ["Review KPIs", "KPIs prüfen"],
      ["Campaign input", "Kampagnen-Eingabe"],
      ["Use presets for QA, private AI, and app modernization. Custom briefs are supported.", "Nutze Vorlagen für QA, Private AI und App-Modernisierung. Eigene Briefings sind möglich."],
      ["Approval quality", "Freigabequalität"],
      ["Brand score must be at least 90 and all checks must pass before scheduler draft creation.", "Brand Score muss mindestens 90 sein und alle Checks müssen bestehen, bevor ein Scheduler-Entwurf entsteht."],
      ["Learning loop", "Lernschleife"],
      ["Use 72h, 7d, 14d, and 30d reviews to decide iterate, fix, stop, or scale.", "Nutze 72h-, 7d-, 14d- und 30d-Reviews für Iterieren, Fixen, Stoppen oder Skalieren."],
      ["Recent States", "Aktuelle Stände"],
      ["Copy Summary", "Zusammenfassung kopieren"],
      ["Content", "Inhalt"],
      ["Campaign", "Kampagne"],
      ["Next", "Nächster Schritt"],
      ["Loading...", "Lädt..."],
      ["Loading", "Lädt"],
      ["Phase Readiness", "Phasenbereitschaft"],
      ["See which implementation phases are finished, partial, or blocked before running campaigns.", "Sieh, welche Umsetzungsphasen fertig, teilweise fertig oder blockiert sind, bevor Kampagnen laufen."],
      ["This is the morning checklist for the marketing machine: core flow, model plane, n8n rhythm, publishing, CRM, creative, and production hardening.", "Das ist die Morgen-Checkliste der Marketingmaschine: Kernablauf, Modell-Ebene, n8n-Rhythmus, Publishing, CRM, Kreativ und Production Hardening."],
      ["Refresh Phases", "Phasen aktualisieren"],
      ["Implementation Phases", "Umsetzungsphasen"],
      ["Phase", "Phase"],
      ["Next action", "Nächste Aktion"],
      ["Raw Phase Report", "Rohdaten Phasenreport"],
      ["Copy", "Kopieren"],
      ["Manual Content Intake", "Manuelle Content-Eingabe"],
      ["Create a campaign brief with proof, CTA, UTM tracking, and a test hypothesis.", "Erstelle ein Kampagnenbriefing mit Beleg, CTA, UTM-Tracking und Testhypothese."],
      ["Use this when someone has a campaign idea, proof asset, offer, customer-safe story, or post request.", "Nutze dies, wenn jemand eine Kampagnenidee, einen Beleg, ein Angebot, eine sichere Kundengeschichte oder einen Postwunsch hat."],
      ["Copy Payload", "Payload kopieren"],
      ["Reset", "Zurücksetzen"],
      ["Campaign Brief", "Kampagnenbriefing"],
      ["Preset", "Vorlage"],
      ["Custom", "Eigene Eingabe"],
      ["Regenerate", "Neu erzeugen"],
      ["Persona", "Persona"],
      ["AI draft language", "Sprache für AI-Entwurf"],
      ["English (US)", "Englisch (USA)"],
      ["Channel", "Kanal"],
      ["Landing Page", "Landingpage"],
      ["Landing page", "Landingpage"],
      ["Format", "Format"],
      ["Expert post", "Expertenpost"],
      ["Video script", "Videoskript"],
      ["App demo post", "App-Demo-Post"],
      ["Test variable", "Testvariable"],
      ["Offer", "Angebot"],
      ["Proof And Offer", "Beleg und Angebot"],
      ["Objective", "Ziel"],
      ["Proof sources", "Belegquellen"],
      ["Hypothesis", "Hypothese"],
      ["Tracking", "Tracking"],
      ["UTM source", "UTM-Quelle"],
      ["UTM medium", "UTM-Medium"],
      ["UTM campaign", "UTM-Kampagne"],
      ["Create Draft", "Entwurf erstellen"],
      ["No publishing from intake", "Kein Publishing aus der Eingabe"],
      ["Readiness Score", "Bereitschaftsscore"],
      ["Live Payload Preview", "Live-Payload-Vorschau"],
      ["Intake Result", "Eingabe-Ergebnis"],
      ["Waiting for draft", "Wartet auf Entwurf"],
      ["Submit a campaign brief to see the draft state.", "Sende ein Kampagnenbriefing ab, um den Entwurfsstand zu sehen."],
      ["Created Post Preview", "Vorschau erstellter Post"],
      ["Copy Post", "Post kopieren"],
      ["Create a draft to see the public post text here.", "Erstelle einen Entwurf, um hier den öffentlichen Posttext zu sehen."],
      ["Human Approval", "Menschliche Freigabe"],
      ["Approve only after checking the draft, proof source, privacy, consent, and AI disclosure.", "Nur freigeben, nachdem Entwurf, Belegquelle, Datenschutz, Einwilligung und AI-Kennzeichnung geprüft wurden."],
      ["This gate keeps public publishing separate from AI drafting. Scheduler output remains draft-only.", "Dieser Schritt trennt öffentliches Publishing sauber vom AI-Entwurf. Scheduler-Ausgaben bleiben nur Entwürfe."],
      ["Load State", "Stand laden"],
      ["Request Revision", "Überarbeitung anfragen"],
      ["Review Decision", "Prüfentscheidung"],
      ["Reviewer", "Prüfer"],
      ["Decision", "Entscheidung"],
      ["Approved", "Freigegeben"],
      ["Minor revision", "Kleine Überarbeitung"],
      ["Major revision", "Große Überarbeitung"],
      ["Rejected", "Abgelehnt"],
      ["Brand score", "Brand Score"],
      ["Publishability", "Veröffentlichbarkeit"],
      ["Needs checks", "Checks nötig"],
      ["Fact check passed", "Faktencheck bestanden"],
      ["Privacy check passed", "Datenschutzcheck bestanden"],
      ["AI disclosure checked", "AI-Kennzeichnung geprüft"],
      ["Notes", "Notizen"],
      ["Apply Approval", "Freigabe anwenden"],
      ["Final Postiz approval still required", "Finale Postiz-Freigabe weiter erforderlich"],
      ["Approval Result", "Freigabe-Ergebnis"],
      ["Waiting for approval", "Wartet auf Freigabe"],
      ["Scheduler Draft Preview", "Scheduler-Entwurfsvorschau"],
      ["Copy Draft", "Entwurf kopieren"],
      ["Approved content will show the draft-only scheduler copy here.", "Freigegebener Content zeigt hier den reinen Entwurf für den Scheduler."],
      ["Approve only after checking proof, consent, brand fit, and claims.", "Nur freigeben, nachdem Beleg, Einwilligung, Markenfit und Aussagen geprüft wurden."],
      ["Lead Intake", "Lead-Eingabe"],
      ["Capture a real response, check consent, score the lead, and prepare CRM/marketing automation payloads.", "Erfasse eine echte Reaktion, prüfe Einwilligung, bewerte den Lead und bereite CRM-/Marketing-Automation-Payloads vor."],
      ["Use this when a post, landing page, email, or direct message creates a business enquiry.", "Nutze dies, wenn ein Post, eine Landingpage, eine E-Mail oder Direktnachricht eine Geschäftsanfrage erzeugt."],
      ["Load Example", "Beispiel laden"],
      ["Refresh Leads", "Leads aktualisieren"],
      ["Lead Details", "Lead-Details"],
      ["Source content ID", "Quell-Content-ID"],
      ["Contact name", "Kontaktname"],
      ["Company", "Firma"],
      ["Email", "E-Mail"],
      ["Phone", "Telefon"],
      ["Message / intent", "Nachricht / Absicht"],
      ["Consent for follow-up is documented", "Einwilligung für Follow-up ist dokumentiert"],
      ["Attribution", "Zuordnung"],
      ["No auto CRM write without credentials", "Kein Auto-CRM-Schreiben ohne Zugangsdaten"],
      ["Lead Result", "Lead-Ergebnis"],
      ["Waiting for lead", "Wartet auf Lead"],
      ["Submit a lead to see score, next action, and CRM/Mautic payloads.", "Sende einen Lead ab, um Score, nächsten Schritt und CRM-/Mautic-Payloads zu sehen."],
      ["Recent Leads", "Aktuelle Leads"],
      ["Lead", "Lead"],
      ["No leads loaded", "Keine Leads geladen"],
      ["Routing Outbox", "Weiterleitungs-Ausgang"],
      ["Prepare approved drafts and qualified leads for external tools with dry-run and audit trail first.", "Bereite freigegebene Entwürfe und qualifizierte Leads zuerst mit Dry-run und Audit-Trail für externe Tools vor."],
      ["Use this after approval or lead scoring. Dry-run is the default; real external writes need explicit server credentials and write enablement.", "Nutze dies nach Freigabe oder Lead-Scoring. Dry-run ist Standard; echte externe Writes brauchen Server-Zugangsdaten und explizite Freischaltung."],
      ["Refresh Outbox", "Ausgang aktualisieren"],
      ["Postiz Draft Route", "Postiz-Entwurfsroute"],
      ["Target", "Ziel"],
      ["Postiz draft", "Postiz-Entwurf"],
      ["Dry-run only", "Nur Dry-run"],
      ["Prepare Postiz Draft", "Postiz-Entwurf vorbereiten"],
      ["Lead Route", "Lead-Route"],
      ["Mautic nurture", "Mautic-Nurturing"],
      ["Prepare Lead Route", "Lead-Route vorbereiten"],
      ["Route Result", "Routen-Ergebnis"],
      ["Waiting for route", "Wartet auf Route"],
      ["Prepare a Postiz draft or lead route to see the outbox record.", "Bereite einen Postiz-Entwurf oder eine Lead-Route vor, um den Ausgangseintrag zu sehen."],
      ["Recent Outbox", "Aktueller Ausgang"],
      ["Source", "Quelle"],
      ["No outbox records loaded", "Keine Ausgangseinträge geladen"],
      ["Optimization Review", "Optimierungsreview"],
      ["Enter performance signals and get a clear decision: scale, iterate, fix landing page, fix audience/offer, or stop.", "Gib Performance-Signale ein und erhalte eine klare Entscheidung: skalieren, iterieren, Landingpage fixen, Zielgruppe/Angebot fixen oder stoppen."],
      ["Do not wait 30 days. Start reading useful signal after 72 hours, then review at 7, 14, and 30 days.", "Warte nicht 30 Tage. Erste nützliche Signale nach 72 Stunden lesen, dann nach 7, 14 und 30 Tagen prüfen."],
      ["Load Weak Signal", "Schwaches Signal laden"],
      ["Load Scale Signal", "Skalierungssignal laden"],
      ["KPI Input", "KPI-Eingabe"],
      ["Review window", "Review-Fenster"],
      ["Impressions", "Impressionen"],
      ["Saves", "Saves"],
      ["Shares", "Shares"],
      ["Buyer comments", "Buyer-Kommentare"],
      ["Profile visits", "Profilbesuche"],
      ["Clicks", "Klicks"],
      ["Qualified leads", "Qualifizierte Leads"],
      ["Booked calls", "Gebuchte Calls"],
      ["Landing visits", "Landingpage-Besuche"],
      ["Landing conversions", "Landingpage-Conversions"],
      ["Pipeline EUR", "Pipeline EUR"],
      ["Evaluate", "Bewerten"],
      ["Waiting for KPI input", "Wartet auf KPI-Eingabe"],
      ["Enter metrics after 72h, 7d, 14d, or 30d.", "Gib Metriken nach 72h, 7d, 14d oder 30d ein."],
      ["Creative Brief", "Kreativbriefing"],
      ["Create a ComfyUI-ready visual brief without auto-submitting generation jobs.", "Erstelle ein ComfyUI-fertiges visuelles Briefing ohne automatische Generierungsjobs."],
      ["Use approved proof assets only. Human visual approval is required before public use.", "Nur freigegebene Beleg-Assets nutzen. Menschliche visuelle Freigabe ist vor öffentlicher Nutzung erforderlich."],
      ["Visual Request", "Visuelle Anfrage"],
      ["Output size", "Ausgabegröße"],
      ["Headline", "Headline"],
      ["Proof asset refs", "Beleg-Asset-Referenzen"],
      ["Create Creative Brief", "Kreativbriefing erstellen"],
      ["Creative Result", "Kreativ-Ergebnis"],
      ["No automatic ComfyUI job submission", "Keine automatische ComfyUI-Jobausführung"],
      ["Creative briefs require human visual approval before use.", "Kreativbriefings benötigen vor Nutzung eine menschliche visuelle Freigabe."],
      ["System Status", "Systemstatus"],
      ["Required services must be green. Kimi is optional backup only.", "Pflichtdienste müssen grün sein. Kimi ist nur optionales Backup."],
      ["Check n8n, ComfyUI, Ollama/Qwen, growth tools, and optional Kimi provider.", "Prüfe n8n, ComfyUI, Ollama/Qwen, Growth Tools und den optionalen Kimi-Provider."],
      ["Refresh Status", "Status aktualisieren"],
      ["Service Summary", "Dienstübersicht"],
      ["Raw Status", "Rohdaten Status"],
      ["Ready", "Bereit"]
    ];

    const i18nAttrPairs = [
      ["title", "Toggle theme", "Design umschalten"],
      ["title", "Refresh recent content", "Aktuelle Inhalte aktualisieren"],
      ["title", "UI language", "UI-Sprache"],
      ["aria-label", "UI language", "UI-Sprache"],
      ["aria-label", "Marketing console sections", "Bereiche der Marketing-Konsole"],
      ["aria-label", "Brief readiness", "Briefing-Bereitschaft"],
      ["placeholder", "Search content ID or campaign", "Content-ID oder Kampagne suchen"],
      ["placeholder", "3 to 5 for Instagram", "3 bis 5 für Instagram"],
      ["placeholder", "approved content ID", "freigegebene Content-ID"],
      ["placeholder", "qualified lead ID", "qualifizierte Lead-ID"],
      ["placeholder", "approved screenshot, consent ref, app proof", "freigegebener Screenshot, Consent-Ref, App-Beleg"],
      ["data-title", "Dashboard", "Übersicht"],
      ["data-title", "Trend Studio", "Trend Studio"],
      ["data-title", "Phase Readiness", "Phasenbereitschaft"],
      ["data-title", "Manual Content Intake", "Manuelle Content-Eingabe"],
      ["data-title", "Human Approval", "Menschliche Freigabe"],
      ["data-title", "Lead Intake", "Lead-Eingabe"],
      ["data-title", "Routing Outbox", "Weiterleitungs-Ausgang"],
      ["data-title", "Optimization Review", "Optimierungsreview"],
      ["data-title", "Creative Brief", "Kreativbriefing"],
      ["data-title", "System Status", "Systemstatus"],
      ["data-description", "A practical command center for creating, approving, and improving WAMOCON marketing campaigns.", "Eine praktische Steuerzentrale zum Erstellen, Freigeben und Verbessern von WAMOCON-Marketingkampagnen."],
      ["data-description", "Pick a campaign, find a useful trend, create Reel options, approve the best draft.", "Kampagne waehlen, Trend finden, Reel-Optionen erstellen und den besten Entwurf freigeben."],
      ["data-description", "Find current ideas, turn them into Reel drafts, and send the best one to review.", "Aktuelle Ideen finden, Reel-Entwuerfe erzeugen und den besten Entwurf zur Pruefung geben."],
      ["data-description", "See which implementation phases are finished, partial, or blocked before running campaigns.", "Sieh, welche Umsetzungsphasen fertig, teilweise fertig oder blockiert sind, bevor Kampagnen laufen."],
      ["data-description", "Create a campaign brief with proof, CTA, UTM tracking, and a test hypothesis.", "Erstelle ein Kampagnenbriefing mit Beleg, CTA, UTM-Tracking und Testhypothese."],
      ["data-description", "Approve only after checking the draft, proof source, privacy, consent, and AI disclosure.", "Nur freigeben, nachdem Entwurf, Belegquelle, Datenschutz, Einwilligung und AI-Kennzeichnung geprüft wurden."],
      ["data-description", "Capture a real response, check consent, score the lead, and prepare CRM/marketing automation payloads.", "Erfasse eine echte Reaktion, prüfe Einwilligung, bewerte den Lead und bereite CRM-/Marketing-Automation-Payloads vor."],
      ["data-description", "Prepare approved drafts and qualified leads for external tools with dry-run and audit trail first.", "Bereite freigegebene Entwürfe und qualifizierte Leads zuerst mit Dry-run und Audit-Trail für externe Tools vor."],
      ["data-description", "Enter performance signals and get a clear decision: scale, iterate, fix landing page, fix audience/offer, or stop.", "Gib Performance-Signale ein und erhalte eine klare Entscheidung: skalieren, iterieren, Landingpage fixen, Zielgruppe/Angebot fixen oder stoppen."],
      ["data-description", "Create a ComfyUI-ready visual brief without auto-submitting generation jobs.", "Erstelle ein ComfyUI-fertiges visuelles Briefing ohne automatische Generierungsjobs."],
      ["data-description", "Required services must be green. Kimi is optional backup only.", "Pflichtdienste müssen grün sein. Kimi ist nur optionales Backup."]
    ];

    const i18nMessages = {
      copied: {de: "In die Zwischenablage kopiert", en: "Copied to clipboard"},
      copyFailed: {de: "Kopieren fehlgeschlagen. Text bitte manuell markieren.", en: "Copy failed. Select the text manually."},
      noMatchingContent: {de: "Kein passender Inhalt", en: "No matching content"},
      noContentYet: {de: "Noch kein Inhalt", en: "No content yet"},
      selected: {de: "Ausgewählt", en: "Selected"},
      noPublicCopy: {de: "Noch kein öffentlicher Posttext verfügbar.", en: "No public post copy available yet."},
      noSchedulerDraft: {de: "Noch kein Scheduler-Entwurf verfügbar.", en: "No scheduler draft available yet."},
      reviewNotes: {de: "Prüfnotizen:", en: "Review notes:"},
      leadExampleLoaded: {de: "Lead-Beispiel geladen", en: "Lead example loaded"},
      noLeadsYet: {de: "Noch keine Leads", en: "No leads yet"},
      noOutboxYet: {de: "Noch keine Ausgangseinträge", en: "No outbox records yet"},
      dryRun: {de: "Dry-run", en: "dry-run"},
      liveWrite: {de: "Live-Write", en: "live write"},
      requiredOk: {de: "Pflichtdienste OK", en: "Required OK"},
      requiredDegraded: {de: "Pflichtdienste gestört", en: "Required degraded"},
      kimiOk: {de: "Kimi OK", en: "Kimi OK"},
      kimiOptional: {de: "Kimi optional", en: "Kimi optional"},
      humanApprovalOn: {de: "Menschliche Freigabe aktiv", en: "Human approval on"},
      requiredIssue: {de: "Pflichtproblem", en: "Required issue"},
      optionalIssue: {de: "Optionales Problem", en: "Optional issue"},
      service: {de: "Dienst", en: "Service"},
      state: {de: "Status", en: "State"},
      complete: {de: "abgeschlossen", en: "complete"},
      partial: {de: "teilweise", en: "partial"},
      blocked: {de: "blockiert", en: "blocked"},
      noPhaseData: {de: "Keine Phasendaten", en: "No phase data"},
      publishableDraft: {de: "Veröffentlichbarer Entwurf", en: "Publishable draft"},
      revisionGate: {de: "Überarbeitungsschritt", en: "Revision gate"},
      weakExampleLoaded: {de: "Schwaches Beispiel geladen", en: "Weak example loaded"},
      scaleExampleLoaded: {de: "Skalierungsbeispiel geladen", en: "Scale example loaded"},
      recentContentRefreshed: {de: "Aktuelle Inhalte aktualisiert", en: "Recent content refreshed"},
      statusRefreshed: {de: "Status aktualisiert", en: "Status refreshed"},
      phasesRefreshed: {de: "Phasenreport aktualisiert", en: "Phase report refreshed"},
      weeklyPlanCreated: {de: "Wochenplan erstellt", en: "Weekly plan created"},
      weeklyPlanPreview: {de: "Wochenplan erstellt. Wähle einen aktuellen Eintrag, um den Posttext zu sehen.", en: "Weekly plan created. Select a recent item to preview its post copy."},
      created: {de: "erstellt", en: "created"},
      issue: {de: "Problem", en: "issue"},
      readyForReview: {de: "Bereit zur Prüfung", en: "Ready for review"},
      draftBlocked: {de: "Entwurf durch Schutzregeln blockiert", en: "Draft blocked by guardrails"},
      draftCreated: {de: "Entwurf erstellt", en: "Draft created"},
      draftBlockedFix: {de: "Entwurf wurde blockiert. Briefing korrigieren und erneut versuchen.", en: "Draft was blocked. Fix the brief and try again."},
      approvalApplied: {de: "Freigabe angewendet", en: "Approval applied"},
      revisionRequired: {de: "Überarbeitung erforderlich", en: "Revision required"},
      approvalFailed: {de: "Freigabe fehlgeschlagen", en: "Approval failed"},
      enterContentId: {de: "Bitte zuerst eine Content-ID eingeben", en: "Enter a content ID first"},
      revisionValuesLoaded: {de: "Überarbeitungswerte geladen", en: "Revision values loaded"},
      decisionPrefix: {de: "Entscheidung", en: "Decision"},
      reviewFailed: {de: "Review fehlgeschlagen", en: "Review failed"},
      leadsRefreshed: {de: "Leads aktualisiert", en: "Leads refreshed"},
      outboxRefreshed: {de: "Ausgang aktualisiert", en: "Outbox refreshed"},
      routeBlocked: {de: "Route blockiert", en: "Route blocked"},
      schedulerRoutePrepared: {de: "Scheduler-Route vorbereitet", en: "Scheduler route prepared"},
      routeFailed: {de: "Route fehlgeschlagen", en: "Route failed"},
      leadRouteBlocked: {de: "Lead-Route blockiert", en: "Lead route blocked"},
      leadRoutePrepared: {de: "Lead-Route vorbereitet", en: "Lead route prepared"},
      crmPayloadReady: {de: "CRM-Payload bereit", en: "CRM payload ready"},
      doNotRoute: {de: "Nicht weiterleiten", en: "Do not route"},
      leadReady: {de: "Lead bereit für Follow-up", en: "Lead ready for follow-up"},
      leadStored: {de: "Lead mit Schutzregel gespeichert", en: "Lead stored with guardrail"},
      leadRejected: {de: "Lead abgelehnt", en: "Lead rejected"},
      creativeBriefCreated: {de: "Kreativbriefing erstellt", en: "Creative brief created"},
      scoreUnit: {de: "Punkte", en: "score"}
    };

    const statusLabels = {
      accepted: {de: "angenommen", en: "accepted"},
      blocked: {de: "blockiert", en: "blocked"},
      check: {de: "Prüfen", en: "Check"},
      complete: {de: "abgeschlossen", en: "complete"},
      compliance_gate: {de: "Compliance-Prüfung", en: "compliance_gate"},
      consent_required: {de: "Einwilligung nötig", en: "consent_required"},
      contact_missing: {de: "Kontakt fehlt", en: "contact_missing"},
      decision: {de: "Entscheidung", en: "decision"},
      degraded: {de: "eingeschränkt", en: "degraded"},
      draft_content: {de: "Entwurf wird erstellt", en: "draft_content"},
      drafting: {de: "in Entwurf", en: "drafting"},
      draft_only_requires_final_platform_approval: {de: "Entwurf, finale Plattformfreigabe nötig", en: "draft_only_requires_final_platform_approval"},
      evidence_gate: {de: "Belegprüfung", en: "evidence_gate"},
      failed: {de: "fehlgeschlagen", en: "failed"},
      human_review: {de: "menschliche Prüfung", en: "human_review"},
      manual_qualification: {de: "manuelle Qualifizierung", en: "manual_qualification"},
      manual_source_review: {de: "Quelle manuell prüfen", en: "manual_source_review"},
      needs_evidence: {de: "Beleg fehlt", en: "needs_evidence"},
      needs_human_review: {de: "menschliche Prüfung nötig", en: "needs_human_review"},
      next: {de: "nächster Schritt", en: "next"},
      "next action": {de: "nächste Aktion", en: "next action"},
      "no scheduler payload": {de: "kein Scheduler-Payload", en: "no scheduler payload"},
      "not ready for scheduler": {de: "noch nicht bereit für Scheduler", en: "not ready for scheduler"},
      nurture_or_disqualify: {de: "nurturen oder disqualifizieren", en: "nurture_or_disqualify"},
      ok: {de: "OK", en: "ok"},
      operational: {de: "betriebsbereit", en: "operational"},
      operational_with_blockers: {de: "betriebsbereit mit Blockern", en: "operational_with_blockers"},
      orchestrator: {de: "Orchestrator", en: "orchestrator"},
      partial: {de: "teilweise", en: "partial"},
      prepared: {de: "vorbereitet", en: "prepared"},
      ready: {de: "bereit", en: "ready"},
      ready_to_schedule: {de: "bereit zur Planung", en: "ready_to_schedule"},
      revision: {de: "Überarbeitung", en: "revision"},
      revision_requested: {de: "Überarbeitung angefragt", en: "revision_requested"},
      route: {de: "Route", en: "route"},
      fix_audience_or_offer: {de: "Zielgruppe oder Angebot fixen", en: "fix_audience_or_offer"},
      fix_landing_page: {de: "Landingpage fixen", en: "fix_landing_page"},
      iterate: {de: "iterieren", en: "iterate"},
      sales_follow_up: {de: "Sales-Follow-up", en: "sales_follow_up"},
      scheduler: {de: "Scheduler", en: "scheduler"},
      sent: {de: "gesendet", en: "sent"},
      scale: {de: "skalieren", en: "scale"},
      status: {de: "Status", en: "status"},
      stop: {de: "stoppen", en: "stop"},
      unknown: {de: "unbekannt", en: "unknown"},
      wait_for_more_data: {de: "mehr Daten abwarten", en: "wait_for_more_data"}
    };

    const i18nLookup = new Map();
    i18nTextPairs.forEach(([en, de]) => {
      i18nLookup.set(en, {en, de});
      i18nLookup.set(de, {en, de});
    });

    const i18nAttrLookup = new Map();
    i18nAttrPairs.forEach(([attr, en, de]) => {
      i18nAttrLookup.set(`${attr}::${en}`, {en, de});
      i18nAttrLookup.set(`${attr}::${de}`, {en, de});
    });

    function t(key) {
      return (i18nMessages[key] && i18nMessages[key][currentUiLanguage]) || key;
    }

    function statusLabel(value) {
      const key = String(value || "").trim();
      return (statusLabels[key] && statusLabels[key][currentUiLanguage]) || key;
    }

    function translateTextNodes(root) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
        acceptNode(node) {
          const parent = node.parentElement;
          if (!parent || ["SCRIPT", "STYLE", "TEXTAREA"].includes(parent.tagName)) return NodeFilter.FILTER_REJECT;
          return node.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
        }
      });
      const nodes = [];
      while (walker.nextNode()) nodes.push(walker.currentNode);
      nodes.forEach((node) => {
        const raw = node.nodeValue;
        const trimmed = raw.trim();
        const entry = i18nLookup.get(trimmed);
        if (entry) node.nodeValue = raw.replace(trimmed, entry[currentUiLanguage]);
      });
    }

    function translateAttributes() {
      ["title", "aria-label", "placeholder", "data-title", "data-description"].forEach((attr) => {
        document.querySelectorAll(`[${attr}]`).forEach((node) => {
          const value = node.getAttribute(attr);
          const entry = i18nAttrLookup.get(`${attr}::${value}`);
          if (entry) node.setAttribute(attr, entry[currentUiLanguage]);
        });
      });
    }

    function applyUiLanguage(language) {
      currentUiLanguage = language === "en" ? "en" : "de";
      document.documentElement.lang = currentUiLanguage;
      document.title = currentUiLanguage === "de" ? "WAMOCON Marketing-Konsole" : "WAMOCON Marketing Console";
      $("uiLanguage").value = currentUiLanguage;
      localStorage.setItem("wamocon-ui-language", currentUiLanguage);
      translateTextNodes(document.body);
      translateAttributes();
      const active = document.querySelector(".screen.active");
      if (active) setScreen(active.id.replace("screen-", ""));
      updatePayloadPreview();
      updatePublishability();
    }

    function showToast(message) {
      const node = $("toast");
      node.textContent = message;
      node.classList.add("show");
      window.clearTimeout(showToast.timer);
      showToast.timer = window.setTimeout(() => node.classList.remove("show"), 2200);
    }

    function iconPill(text, mode = "neutral") {
      return `<span class="pill ${mode}">${escapeHtml(text)}</span>`;
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;"
      }[char]));
    }

    function setJson(id, value) {
      const formatted = typeof value === "string" ? value : JSON.stringify(value, null, 2);
      $(id).textContent = formatted;
      lastResult[id] = formatted;
    }

    async function copyText(text) {
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
        showToast(t("copied"));
      } catch {
        showToast(t("copyFailed"));
      }
    }

    async function postJson(path, payload) {
      const response = await fetch(path, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });
      const text = await response.text();
      let data;
      try { data = text ? JSON.parse(text) : {}; } catch { data = {raw: text}; }
      if (!response.ok) throw new Error(JSON.stringify(data, null, 2));
      return data;
    }

    async function getJson(path) {
      const response = await fetch(path);
      const data = await response.json();
      if (!response.ok) throw new Error(JSON.stringify(data, null, 2));
      return data;
    }

    function currentPreset() {
      return presets[$("preset").value] || presets.k1;
    }

    function applyPreset(key, keepId = false) {
      const preset = presets[key] || presets.k1;
      if (!keepId) $("contentId").value = `${preset.idPrefix}-${stamp()}`;
      $("campaign").value = preset.campaign;
      $("persona").value = preset.persona;
      $("channel").value = preset.channel;
      $("format").value = preset.format;
      $("language").value = preset.language || "de-DE";
      $("objective").value = preset.objective;
      $("cta").value = preset.cta;
      $("proofSources").value = preset.proof_sources;
      $("hypothesis").value = preset.hypothesis;
      $("testVariable").value = preset.test_variable;
      $("utmSource").value = preset.utm_source;
      $("utmMedium").value = preset.utm_medium;
      $("utmCampaign").value = preset.utm_campaign;
      updatePayloadPreview();
    }

    function intakePayload() {
      return {
        id: $("contentId").value.trim(),
        campaign: $("campaign").value.trim(),
        persona: $("persona").value.trim(),
        channel: $("channel").value,
        format: $("format").value,
        language: $("language").value,
        objective: $("objective").value.trim(),
        cta: $("cta").value.trim(),
        proof_sources: splitList($("proofSources").value),
        utm: {
          utm_source: $("utmSource").value.trim(),
          utm_medium: $("utmMedium").value.trim(),
          utm_campaign: $("utmCampaign").value.trim()
        },
        hypothesis: $("hypothesis").value.trim(),
        test_variable: $("testVariable").value,
        hashtags: splitList($("hashtags").value)
      };
    }

    function germanCopyLooksReady(payload) {
      if (!String(payload.language || "").toLowerCase().startsWith("de")) return true;
      const fields = [payload.objective, payload.cta, payload.hypothesis].join(" ").toLowerCase();
      return !/(^|\\s)(promote|proof-led|without|sending|company data|public ai systems|validate|mock data|book|discovery call|buyer|interest|qualified|outperforms|generates|will)(\\s|$)/i.test(fields);
    }

    function validateBrief(payload) {
      const checks = [
        {label: currentUiLanguage === "de" ? "Content-ID vorhanden" : "Content ID exists", ok: Boolean(payload.id)},
        {label: currentUiLanguage === "de" ? "Kampagne und Persona ausgewählt" : "Campaign and persona selected", ok: Boolean(payload.campaign && payload.persona)},
        {label: currentUiLanguage === "de" ? "Sprache für AI-Entwurf ausgewählt" : "AI draft language selected", ok: Boolean(payload.language)},
        {label: currentUiLanguage === "de" ? "Deutsches Briefing nutzt deutsche Marktsprache" : "German brief uses German market wording", ok: germanCopyLooksReady(payload)},
        {label: currentUiLanguage === "de" ? "Ziel und CTA sind klar" : "Objective and CTA are clear", ok: Boolean(payload.objective && payload.cta)},
        {label: currentUiLanguage === "de" ? "Mindestens eine Belegquelle" : "At least one proof source", ok: payload.proof_sources.length > 0},
        {label: currentUiLanguage === "de" ? "UTM-Quelle, Medium und Kampagne vollständig" : "UTM source, medium, campaign complete", ok: Boolean(payload.utm.utm_source && payload.utm.utm_medium && payload.utm.utm_campaign)},
        {label: currentUiLanguage === "de" ? "Hypothese und Testvariable vorhanden" : "Hypothesis and test variable present", ok: Boolean(payload.hypothesis && payload.test_variable)},
        {label: currentUiLanguage === "de" ? "Instagram-Hashtags <= 5" : "Instagram hashtags <= 5", ok: payload.channel.toLowerCase() !== "instagram" || payload.hashtags.length <= 5}
      ];
      const passed = checks.filter((item) => item.ok).length;
      return {checks, score: Math.round((passed / checks.length) * 100)};
    }

    function updatePayloadPreview() {
      const payload = intakePayload();
      const quality = validateBrief(payload);
      $("payloadPreview").textContent = JSON.stringify(payload, null, 2);
      $("qualityBar").style.width = `${quality.score}%`;
      $("qualityScore").textContent = currentUiLanguage === "de" ? `${quality.score}% bereit` : `${quality.score}% ready`;
      $("qualityScore").className = `pill ${quality.score >= 90 ? "ok" : quality.score >= 70 ? "warn" : "bad"}`;
      $("qualityChecks").innerHTML = quality.checks.map((item) =>
        `<div class="check ${item.ok ? "ok" : "bad"}"><span>${escapeHtml(item.label)}</span><strong>${item.ok ? "OK" : currentUiLanguage === "de" ? "Fixen" : "Fix"}</strong></div>`
      ).join("");
    }

    function setScreen(screen) {
      document.querySelectorAll(".nav-tab").forEach((node) => node.setAttribute("aria-selected", String(node.dataset.screen === screen)));
      document.querySelectorAll(".screen").forEach((node) => node.classList.toggle("active", node.id === `screen-${screen}`));
      const active = $(`screen-${screen}`);
      $("screenTitle").textContent = active.dataset.title || "Console";
      $("screenDescription").textContent = active.dataset.description || "";
      $("activeModePill").textContent = active.dataset.title || screen;
      window.history.replaceState(null, "", `#${screen}`);
    }

    function updateRecentViews() {
      const query = $("recentSearch").value.trim().toLowerCase();
      const filtered = recentItems.filter((item) => {
        const haystack = `${item.content_id} ${item.campaign} ${item.status} ${item.next_step}`.toLowerCase();
        return !query || haystack.includes(query);
      });

      $("recentList").innerHTML = filtered.length ? filtered.map((item) => `
        <button type="button" class="recent-item" data-content-id="${escapeHtml(item.content_id)}">
          <strong>${escapeHtml(item.content_id)}</strong>
          <span>${escapeHtml(item.campaign || "Campaign")} | ${escapeHtml(statusLabel(item.status || "status"))} | ${escapeHtml(statusLabel(item.next_step || "next"))}</span>
        </button>
      `).join("") : `<span class="pill warn">${t("noMatchingContent")}</span>`;

      $("recentTableBody").innerHTML = filtered.slice(0, 10).map((item) => `
        <tr>
          <td>${escapeHtml(item.content_id)}</td>
          <td>${escapeHtml(item.campaign || "")}</td>
          <td>${escapeHtml(statusLabel(item.status || ""))}</td>
          <td>${escapeHtml(statusLabel(item.next_step || ""))}</td>
        </tr>
      `).join("") || `<tr><td colspan="4">${t("noContentYet")}</td></tr>`;

      document.querySelectorAll(".recent-item").forEach((button) => {
        button.addEventListener("click", () => selectContent(button.dataset.contentId));
      });

      $("metricRecent").textContent = String(recentItems.length);
      $("metricReview").textContent = String(recentItems.filter((item) => item.requires_human_review).length);
    }

    async function refreshRecent() {
      const data = await getJson("/workflows/states?limit=30");
      recentItems = data.items || [];
      updateRecentViews();
      return recentItems;
    }

    async function selectContent(contentId) {
      $("approvalContentId").value = contentId;
      $("analyticsContentId").value = contentId;
      $("leadSourceContentId").value = contentId;
      $("routeContentId").value = contentId;
      setScreen("approval");
      showToast(`${t("selected")} ${contentId}`);
      try {
        const state = await getJson(`/workflows/states/${encodeURIComponent(contentId)}`);
        renderApprovalResult(state);
        renderApprovalSummary(state);
        renderPostPreview(state);
        renderSchedulerPreview(state);
      } catch (error) {
        setJson("approvalResult", String(error.message || error));
      }
    }

    function selectedTrendPlatforms() {
      return Array.from(document.querySelectorAll("#trendPlatforms input:checked")).map((node) => node.value);
    }

    function trendScanPayload() {
      return {
        lookback_days: intValue("trendLookback") || 10,
        limit_per_campaign: intValue("trendLimit") || 4,
        platforms: selectedTrendPlatforms()
      };
    }

    function renderTrendRun(data) {
      const run = data.trend_run || data;
      activeTrendRun = run;
      activeTrendSelection = null;
      activeTrendConcept = null;
      const campaignCount = (run.campaigns || []).length;
      const trendCount = (run.campaigns || []).reduce((sum, item) => sum + ((item.trends || []).length), 0);
      const hasSources = (run.source_adapters || []).length > 0;
      $("trendRunSummary").innerHTML = [
        iconPill(run.status === "verified_sources" ? "Live sources ready" : "Connect live sources", run.status === "verified_sources" ? "ok" : "warn"),
        iconPill(`${campaignCount} campaigns`, "neutral"),
        iconPill(`${trendCount} ideas`, "neutral"),
        iconPill(hasSources ? "real source scan" : "demo scan", hasSources ? "ok" : "warn")
      ].join("");
      $("trendRunResult").textContent = [
        `Scan ID: ${run.id || ""}`,
        `Status: ${run.status === "verified_sources" ? "Live source scan ready" : "Demo mode until source keys are connected"}`,
        `Campaigns checked: ${campaignCount}`,
        `Ideas found: ${trendCount}`,
        `Sources: ${hasSources ? run.source_adapters.join(", ") : "No live source keys connected yet"}`,
        "",
        hasSources ? "You can use these ideas as current trend signals after review." : "You can test the workflow now. Add search/social keys for real latest trend results."
      ].join("\\n");
      $("trendConceptSummary").innerHTML = iconPill("Select idea", "neutral");
      $("trendConceptResult").textContent = "Choose a campaign idea, then create Reel options.";
      $("trendSelectedPill").textContent = "Select idea";
      $("trendCampaigns").innerHTML = (run.campaigns || []).map((item) => {
        const campaign = item.campaign || {};
        const rows = (item.trends || []).map((trend) => {
          const verification = trend.verification || {};
          const mode = verification.status === "verified_recent" ? "ok" : verification.status === "requires_live_sources" ? "bad" : "warn";
          return `
            <button type="button" class="recent-item trend-item" data-campaign-id="${escapeHtml(campaign.id || "")}" data-trend-id="${escapeHtml(trend.id || "")}">
              <strong>${escapeHtml(trend.topic || "Trend")}</strong>
              <span>${escapeHtml(campaign.name || "")} | ${escapeHtml(statusLabel(verification.status || ""))} | score ${escapeHtml(String(trend.score || 0))}</span>
            </button>
          `;
        }).join("");
        return `<div class="stack"><h3>${escapeHtml(campaign.name || "Campaign")}</h3>${rows || `<span class="pill warn">No ideas</span>`}</div>`;
      }).join("") || `<span class="pill warn">No ideas loaded</span>`;
      document.querySelectorAll(".trend-item").forEach((button) => {
        button.addEventListener("click", () => selectTrend(button.dataset.campaignId, button.dataset.trendId));
      });
    }

    function selectTrend(campaignId, trendId) {
      if (!activeTrendRun) return;
      const campaignItem = (activeTrendRun.campaigns || []).find((item) => item.campaign?.id === campaignId);
      const trend = (campaignItem?.trends || []).find((item) => item.id === trendId);
      if (!campaignItem || !trend) return;
      activeTrendSelection = {campaignId, trendId, campaign: campaignItem.campaign, trend};
      activeTrendConcept = null;
      const verification = trend.verification || {};
      $("trendSelectedPill").textContent = trend.topic || "Trend";
      $("trendConceptSummary").innerHTML = [
        iconPill(campaignItem.campaign?.name || "Campaign", "neutral"),
        iconPill(statusLabel(verification.status || "status"), verification.status === "verified_recent" ? "ok" : "warn"),
        iconPill(`${verification.evidence_count || 0} sources`, verification.evidence_count >= 2 ? "ok" : "warn")
      ].join("");
      $("trendConceptResult").textContent = [
        `Selected idea: ${trend.topic || ""}`,
        `Campaign: ${campaignItem.campaign?.name || ""}`,
        `Why it fits: ${trend.campaign_fit || ""}`,
        `Source status: ${verification.status === "verified_recent" ? "recent sources found" : verification.note || verification.status || "review needed"}`,
        "",
        "Suggested Reel angles:",
        ...(trend.format_suggestions || []).slice(0, 4).map((format) => `- ${format}`),
        "",
        "Next: click Create Ideas."
      ].join("\\n");
    }

    function renderConceptResult(concept) {
      const variants = concept.variants || [];
      $("trendConceptResult").textContent = [
        `Reel idea bundle: ${concept.id || ""}`,
        `Campaign: ${concept.campaign?.name || ""}`,
        `Selected trend: ${concept.trend?.topic || ""}`,
        "",
        "Best options:",
        ...variants.map((variant, index) => [
          `${index + 1}. ${variant.format || "Reel option"}`,
          `   Hook: ${variant.hook || ""}`,
          `   CTA: ${variant.cta || ""}`,
          `   Edit style: ${variant.animation_notes || ""}`,
        ].join("\\n")),
        "",
        "Next: Send First To Review, or adjust the direction and Create Ideas again."
      ].join("\\n");
    }

    async function generateTrendConceptBundle() {
      if (!activeTrendRun || !activeTrendSelection) {
        $("trendConceptSummary").innerHTML = iconPill("Select trend first", "warn");
        return;
      }
      const data = await postJson("/workflows/reel-concepts", {
        run_id: activeTrendRun.id,
        campaign_id: activeTrendSelection.campaignId,
        trend_id: activeTrendSelection.trendId,
        user_prompt: $("trendUserPrompt").value.trim(),
        variant_count: intValue("trendVariantCount") || 4
      });
      activeTrendConcept = data.concept;
      $("trendConceptSummary").innerHTML = [
        iconPill("Concept created", "ok"),
        iconPill(`${activeTrendConcept.variants.length} variants`, "neutral"),
        iconPill(activeTrendConcept.status || "draft", "warn")
      ].join("");
      renderConceptResult(activeTrendConcept);
    }

    async function approveActiveTrendConcept() {
      if (!activeTrendConcept) {
        $("trendConceptSummary").innerHTML = iconPill("Generate concept first", "warn");
        return;
      }
      const firstVariant = activeTrendConcept.variants?.[0] || {};
      const data = await postJson(`/workflows/reel-concepts/${encodeURIComponent(activeTrendConcept.id)}/approve`, {
        variant_id: firstVariant.id || ""
      });
      $("approvalContentId").value = data.content_id || "";
      $("analyticsContentId").value = data.content_id || "";
      $("leadSourceContentId").value = data.content_id || "";
      $("routeContentId").value = data.content_id || "";
      $("trendConceptSummary").innerHTML = [
        iconPill("Approved to review", "ok"),
        iconPill(data.content_id || "content", "neutral"),
        iconPill(statusLabel(data.state?.brief?.status || ""), "warn")
      ].join("");
      $("trendConceptResult").textContent = [
        `Sent to review: ${data.content_id || ""}`,
        `Status: ${statusLabel(data.state?.brief?.status || "")}`,
        "",
        "Open the Approval screen to check proof, brand fit, privacy, and AI disclosure."
      ].join("\\n");
      renderApprovalResult(data);
      renderApprovalSummary(data);
      renderPostPreview(data);
      renderSchedulerPreview(data);
      await refreshRecent();
      setScreen("approval");
    }

    function renderApprovalSummary(data) {
      const state = data.state || data;
      const nextStep = state.next_step || "unknown";
      const status = state.brief?.status || "unknown";
      const scheduler = state.scheduler_payload?.status || "no scheduler payload";
      $("approvalSummary").innerHTML = [
        iconPill(statusLabel(status), status.includes("ready") ? "ok" : status.includes("blocked") ? "bad" : "warn"),
        iconPill(statusLabel(nextStep), nextStep === "scheduler" ? "ok" : "neutral"),
        iconPill(statusLabel(scheduler), scheduler.includes("draft") ? "warn" : "neutral")
      ].join("");
    }

    function renderApprovalResult(data) {
      const state = data.state || data;
      const brief = state.brief || {};
      const concept = brief.reel_concept || {};
      const approval = state.approval || {};
      const errors = state.errors || [];
      const proofCount = (brief.proof_sources || []).length;
      const label = (de, en) => currentUiLanguage === "de" ? de : en;
      const checkLines = [
        approval.fact_check_passed ? label("- Faktencheck bestanden", "- Fact check passed") : "",
        approval.privacy_check_passed ? label("- Datenschutz geprueft", "- Privacy checked") : "",
        approval.ai_disclosure_check_passed ? label("- AI-Kennzeichnung geprueft", "- AI disclosure checked") : ""
      ].filter(Boolean);
      $("approvalResult").textContent = [
        `${label("Status", "Status")}: ${statusLabel(brief.status || "unknown")}`,
        `${label("Naechster Schritt", "Next step")}: ${statusLabel(state.next_step || "unknown")}`,
        `${label("Kampagne", "Campaign")}: ${brief.campaign || ""}`,
        concept.format ? `${label("Reel-Format", "Reel format")}: ${concept.format}` : "",
        concept.hook ? `${label("Hook", "Hook")}: ${concept.hook}` : "",
        brief.cta ? `${label("CTA", "CTA")}: ${brief.cta}` : "",
        "",
        errors.length ? label("Bitte klaeren:", "Needs attention:") : label("Freigabecheck:", "Approval check:"),
        ...(errors.length ? errors.map((error) => `- ${statusLabel(error)}`) : [
          label("- Bereit fuer den naechsten Schritt.", "- Ready for the next step."),
          proofCount ? label(`- ${proofCount} Belegquelle(n) hinterlegt.`, `- ${proofCount} proof source(s) attached.`) : "",
          ...checkLines
        ].filter(Boolean)),
        "",
        `${label("Entwurf", "Draft")}: ${brief.id || data.content_id || ""}`
      ].filter((line) => line !== "").join("\\n");
    }

    function postCopyFrom(data) {
      const state = data.state || data;
      return state.scheduler_payload?.copy || state.brief?.public_copy || state.brief?.draft || "";
    }

    function renderPostPreview(data) {
      const copy = postCopyFrom(data);
      $("postPreview").textContent = copy || t("noPublicCopy");
    }

    function renderSchedulerPreview(data) {
      const state = data.state || data;
      const copy = state.scheduler_payload?.copy || state.brief?.public_copy || "";
      const notes = state.scheduler_payload?.review_notes || state.brief?.review_notes || [];
      const status = state.scheduler_payload?.status || "not ready for scheduler";
      $("schedulerPreview").textContent = [
        `Status: ${statusLabel(status)}`,
        "",
        copy || t("noSchedulerDraft"),
        "",
        notes.length ? t("reviewNotes") : "",
        ...notes.map((note) => `- ${note}`)
      ].filter(Boolean).join("\\n");
    }

    function leadPayload() {
      return {
        id: $("leadId").value.trim(),
        source_content_id: $("leadSourceContentId").value.trim(),
        campaign: $("leadCampaign").value.trim(),
        offer: $("leadOffer").value.trim(),
        persona: $("leadPersona").value.trim(),
        contact_name: $("leadContactName").value.trim(),
        company: $("leadCompany").value.trim(),
        email: $("leadEmail").value.trim(),
        phone: $("leadPhone").value.trim(),
        message: $("leadMessage").value.trim(),
        consent_given: $("leadConsent").checked,
        utm: {
          utm_source: $("leadUtmSource").value.trim(),
          utm_medium: $("leadUtmMedium").value.trim(),
          utm_campaign: $("leadUtmCampaign").value.trim()
        }
      };
    }

    function setLeadExample() {
      const contentId = $("leadSourceContentId").value.trim() || $("approvalContentId").value.trim() || $("analyticsContentId").value.trim() || $("contentId").value.trim();
      $("leadId").value = `lead-${stamp()}`;
      $("leadSourceContentId").value = contentId;
      $("leadCampaign").value = $("campaign").value.trim() || "K1 QA Consulting";
      $("leadOffer").value = $("cta").value.trim() || "QA-Risikoaudit";
      $("leadPersona").value = $("persona").value.trim() || "IT-Leiter Thomas";
      $("leadContactName").value = "Max Mustermann";
      $("leadCompany").value = "Muster GmbH";
      $("leadEmail").value = "it-leitung@muster-gmbh.de";
      $("leadPhone").value = "";
      $("leadMessage").value = "Wir möchten einen QA-Risikoaudit Termin anfragen.";
      $("leadConsent").checked = true;
      $("leadUtmSource").value = $("utmSource").value.trim() || "linkedin";
      $("leadUtmMedium").value = $("utmMedium").value.trim() || "organic";
      $("leadUtmCampaign").value = $("utmCampaign").value.trim() || "k1_qa_risk_audit";
      showToast(t("leadExampleLoaded"));
    }

    function updateLeadTable() {
      $("leadTableBody").innerHTML = recentLeads.length ? recentLeads.map((item) => `
        <tr>
          <td>${escapeHtml(item.id || "")}</td>
          <td>${escapeHtml(item.campaign || "")}</td>
          <td>${escapeHtml(item.company || "")}</td>
          <td>${escapeHtml(statusLabel(item.next_action || ""))}</td>
        </tr>
      `).join("") : `<tr><td colspan="4">${t("noLeadsYet")}</td></tr>`;
    }

    async function refreshLeadList() {
      const data = await getJson("/workflows/leads?limit=20");
      recentLeads = data.items || [];
      updateLeadTable();
      return recentLeads;
    }

    function updateOutboxTable() {
      $("outboxTableBody").innerHTML = recentOutbox.length ? recentOutbox.map((item) => `
        <tr>
          <td>${escapeHtml(item.id || "")}</td>
          <td>${escapeHtml(item.target || "")}</td>
          <td>${escapeHtml(statusLabel(item.status || ""))}</td>
          <td>${escapeHtml(item.source_id || "")}</td>
        </tr>
      `).join("") : `<tr><td colspan="4">${t("noOutboxYet")}</td></tr>`;
    }

    async function refreshOutboxList() {
      const data = await getJson("/workflows/outbox?limit=20");
      recentOutbox = data.items || [];
      updateOutboxTable();
      return recentOutbox;
    }

    function renderRouteResult(data) {
      const route = data.route || {};
      const mode = route.status === "sent" || route.status === "prepared" ? "ok" : route.status === "blocked" ? "bad" : "warn";
      $("routeSummary").innerHTML = [
        iconPill(statusLabel(route.status || "route"), mode),
        iconPill(route.target || "target", "neutral"),
        iconPill(route.dry_run ? t("dryRun") : t("liveWrite"), route.dry_run ? "warn" : "ok")
      ].join("");
      setJson("routeResult", data);
    }

    async function refreshStatus() {
      const data = await getJson("/integrations/status");
      setJson("statusResult", data);
      const requiredOk = (data.required || []).every((item) => item.ok);
      const kimi = (data.checks || []).find((item) => item.name === "kimi");
      $("healthPills").innerHTML = [
        iconPill(requiredOk ? t("requiredOk") : t("requiredDegraded"), requiredOk ? "ok" : "bad"),
        iconPill(kimi && kimi.ok ? t("kimiOk") : t("kimiOptional"), kimi && kimi.ok ? "ok" : "warn"),
        iconPill(t("humanApprovalOn"), "ok")
      ].join("");
      $("metricRequired").textContent = requiredOk ? "OK" : statusLabel("check");
      $("metricRequired").style.color = requiredOk ? "var(--green)" : "var(--red)";
      $("metricGuard").style.color = "var(--green)";
      $("serviceSummary").innerHTML = `<table class="mini-table"><thead><tr><th>${t("service")}</th><th>${t("state")}</th><th>URL</th></tr></thead><tbody>${
        (data.checks || []).map((item) => `<tr><td>${escapeHtml(item.name)}</td><td>${item.ok ? iconPill("OK", "ok") : iconPill(item.required ? t("requiredIssue") : t("optionalIssue"), item.required ? "bad" : "warn")}</td><td>${escapeHtml(item.url || "")}</td></tr>`).join("")
      }</tbody></table>`;
    }

    async function refreshPhaseStatus() {
      const data = await getJson("/workflows/phase-status");
      phaseItems = data.phases || [];
      setJson("phaseResult", data);
      $("phaseSummary").innerHTML = [
        iconPill(statusLabel(data.status || "status"), data.status === "operational" ? "ok" : data.status === "blocked" ? "bad" : "warn"),
        iconPill(`${data.summary?.complete || 0} ${t("complete")}`, "ok"),
        iconPill(`${data.summary?.partial || 0} ${t("partial")}`, "warn"),
        iconPill(`${data.summary?.blocked || 0} ${t("blocked")}`, (data.summary?.blocked || 0) ? "bad" : "neutral")
      ].join("");
      $("phaseTableBody").innerHTML = phaseItems.map((phase) => {
        const mode = phase.status === "complete" ? "ok" : phase.status === "blocked" ? "bad" : "warn";
        const next = (phase.next_actions || []).join(" | ") || t("ready");
        return `<tr><td><strong>${escapeHtml(phase.name)}</strong><br><span class="subtle">${escapeHtml(phase.id)}</span></td><td>${iconPill(statusLabel(phase.status), mode)}</td><td>${escapeHtml(next)}</td></tr>`;
      }).join("") || `<tr><td colspan="3">${t("noPhaseData")}</td></tr>`;
      return data;
    }

    function approvalPayload() {
      return {
        content_id: $("approvalContentId").value.trim(),
        reviewer: $("reviewer").value.trim(),
        decision: $("decision").value,
        brand_score: intValue("brandScore"),
        fact_check_passed: $("factCheck").checked,
        privacy_check_passed: $("privacyCheck").checked,
        ai_disclosure_check_passed: $("disclosureCheck").checked,
        notes: $("approvalNotes").value.trim()
      };
    }

    function updatePublishability() {
      const payload = approvalPayload();
      const ok = payload.decision === "approved" && payload.brand_score >= 90 && payload.fact_check_passed && payload.privacy_check_passed && payload.ai_disclosure_check_passed;
      $("publishabilityPill").textContent = ok ? t("publishableDraft") : t("revisionGate");
      $("publishabilityPill").className = `pill ${ok ? "ok" : "warn"}`;
    }

    function analyticsPayload() {
      return {
        content_id: $("analyticsContentId").value.trim(),
        review_window: $("reviewWindow").value,
        impressions: intValue("impressions"),
        saves: intValue("saves"),
        shares: intValue("shares"),
        comments_from_target_buyers: intValue("buyerComments"),
        profile_visits: intValue("profileVisits"),
        clicks: intValue("clicks"),
        leads: intValue("leads"),
        qualified_leads: intValue("qualifiedLeads"),
        booked_calls: intValue("bookedCalls"),
        landing_page_visits: intValue("landingVisits"),
        landing_page_conversions: intValue("landingConversions"),
        pipeline_value_eur: floatValue("pipelineValue")
      };
    }

    function setAnalyticsExample(kind) {
      if (kind === "scale") {
        $("reviewWindow").value = "30d";
        $("impressions").value = "2400";
        $("saves").value = "24";
        $("shares").value = "8";
        $("buyerComments").value = "3";
        $("profileVisits").value = "80";
        $("clicks").value = "52";
        $("leads").value = "5";
        $("qualifiedLeads").value = "3";
        $("bookedCalls").value = "2";
        $("landingVisits").value = "52";
        $("landingConversions").value = "5";
        $("pipelineValue").value = "18000";
      } else {
        $("reviewWindow").value = "72h";
        $("impressions").value = "120";
        $("saves").value = "0";
        $("shares").value = "0";
        $("buyerComments").value = "0";
        $("profileVisits").value = "3";
        $("clicks").value = "0";
        $("leads").value = "0";
        $("qualifiedLeads").value = "0";
        $("bookedCalls").value = "0";
        $("landingVisits").value = "0";
        $("landingConversions").value = "0";
        $("pipelineValue").value = "0";
      }
      showToast(kind === "scale" ? t("scaleExampleLoaded") : t("weakExampleLoaded"));
    }

    document.querySelectorAll(".nav-tab").forEach((button) => button.addEventListener("click", () => setScreen(button.dataset.screen)));
    document.querySelectorAll("[data-jump]").forEach((button) => button.addEventListener("click", () => setScreen(button.dataset.jump)));
    document.querySelectorAll("[data-copy]").forEach((button) => button.addEventListener("click", () => copyText($(button.dataset.copy).textContent)));

    $("themeToggle").addEventListener("click", () => {
      document.body.classList.toggle("theme-dark");
      localStorage.setItem("wamocon-theme", document.body.classList.contains("theme-dark") ? "dark" : "light");
    });
    $("uiLanguage").addEventListener("change", (event) => applyUiLanguage(event.target.value));

    $("preset").addEventListener("change", (event) => {
      if (event.target.value !== "custom") applyPreset(event.target.value);
    });
    $("regenId").addEventListener("click", () => {
      $("contentId").value = `${currentPreset().idPrefix || "custom"}-${stamp()}`;
      updatePayloadPreview();
    });
    $("resetIntake").addEventListener("click", () => applyPreset("k1"));
    $("copyPayloadPreview").addEventListener("click", () => copyText($("payloadPreview").textContent));
    $("clearRecentSearch").addEventListener("click", () => {
      $("recentSearch").value = "";
      updateRecentViews();
    });
    $("recentSearch").addEventListener("input", updateRecentViews);
    $("refreshRecent").addEventListener("click", () => refreshRecent().then(() => showToast(t("recentContentRefreshed"))));
    $("refreshStatus").addEventListener("click", () => refreshStatus().then(() => showToast(t("statusRefreshed"))));
    $("refreshPhases").addEventListener("click", () => refreshPhaseStatus().then(() => showToast(t("phasesRefreshed"))));
    $("runTrendScan").addEventListener("click", async () => {
      try {
        $("trendRunSummary").innerHTML = iconPill("Scanning", "warn");
        const data = await postJson("/workflows/trend-research", trendScanPayload());
        renderTrendRun(data);
        showToast("Trend scan finished");
      } catch (error) {
        $("trendRunSummary").innerHTML = iconPill("Trend scan failed", "bad");
        setJson("trendRunResult", String(error.message || error));
      }
    });
    $("refreshTrendRuns").addEventListener("click", async () => {
      try {
        const data = await getJson("/workflows/trend-research/runs?limit=10");
        setJson("trendRunResult", data);
        $("trendRunSummary").innerHTML = iconPill(`${(data.items || []).length} saved runs`, "neutral");
      } catch (error) {
        setJson("trendRunResult", String(error.message || error));
      }
    });
    $("generateTrendConcept").addEventListener("click", async () => {
      try {
        await generateTrendConceptBundle();
        showToast("Reel concepts generated");
      } catch (error) {
        $("trendConceptSummary").innerHTML = iconPill("Concept blocked", "bad");
        setJson("trendConceptResult", String(error.message || error));
      }
    });
    $("approveTrendConcept").addEventListener("click", async () => {
      try {
        await approveActiveTrendConcept();
        showToast("Concept approved into review queue");
      } catch (error) {
        $("trendConceptSummary").innerHTML = iconPill("Approval failed", "bad");
        setJson("trendConceptResult", String(error.message || error));
      }
    });
      $("weeklyPlanTop").addEventListener("click", async () => {
      const data = await postJson("/workflows/weekly-planning", {calendar_mode: "rolling_30_day"});
      setJson("intakeResult", data);
      $("intakeSummary").innerHTML = iconPill(t("weeklyPlanCreated"), "ok");
      $("postPreview").textContent = t("weeklyPlanPreview");
      await refreshRecent();
      showToast(t("weeklyPlanCreated"));
    });
    $("copyRecentSummary").addEventListener("click", () => copyText(JSON.stringify(recentItems.slice(0, 10), null, 2)));

    ["input", "change"].forEach((eventName) => {
      $("intakeForm").addEventListener(eventName, updatePayloadPreview);
      $("approvalForm").addEventListener(eventName, updatePublishability);
    });

    $("intakeForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const payload = intakePayload();
        const data = await postJson("/workflows/create-content", payload);
        $("approvalContentId").value = payload.id;
        $("analyticsContentId").value = payload.id;
        $("leadSourceContentId").value = payload.id;
        $("routeContentId").value = payload.id;
        const errors = data.state?.errors || [];
        $("intakeSummary").innerHTML = [
          iconPill(statusLabel(data.state?.brief?.status || t("created")), errors.length ? "bad" : "ok"),
          iconPill(statusLabel(data.state?.next_step || "next"), "neutral"),
          errors.length ? iconPill(`${errors.length} ${t("issue")}`, "bad") : iconPill(t("readyForReview"), "ok")
        ].join("");
        setJson("intakeResult", data);
        renderPostPreview(data);
        renderSchedulerPreview(data);
        await refreshRecent();
        showToast(errors.length ? t("draftBlocked") : t("draftCreated"));
      } catch (error) {
        $("intakeSummary").innerHTML = iconPill("Blocked", "bad");
        setJson("intakeResult", String(error.message || error));
        $("postPreview").textContent = t("draftBlockedFix");
      }
    });

    $("approvalForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const data = await postJson("/workflows/approve-content", approvalPayload());
        renderApprovalSummary(data);
        renderSchedulerPreview(data);
        renderApprovalResult(data);
        await refreshRecent();
        showToast(data.state?.next_step === "scheduler" ? t("approvalApplied") : t("revisionRequired"));
      } catch (error) {
        $("approvalSummary").innerHTML = iconPill(t("approvalFailed"), "bad");
        setJson("approvalResult", String(error.message || error));
      }
    });

    $("loadApprovalState").addEventListener("click", async () => {
      const contentId = $("approvalContentId").value.trim();
      if (!contentId) return showToast(t("enterContentId"));
      try {
        const state = await getJson(`/workflows/states/${encodeURIComponent(contentId)}`);
        renderApprovalSummary(state);
        renderPostPreview(state);
        renderSchedulerPreview(state);
        renderApprovalResult(state);
      } catch (error) {
        setJson("approvalResult", String(error.message || error));
      }
    });

    $("requestRevision").addEventListener("click", () => {
      $("decision").value = "minor_revision";
      $("brandScore").value = "70";
      $("factCheck").checked = false;
      $("approvalNotes").value = currentUiLanguage === "de" ? "Überarbeitung vor Planung angefragt." : "Revision requested before scheduling.";
      updatePublishability();
      showToast(t("revisionValuesLoaded"));
    });

    $("analyticsForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const data = await postJson("/workflows/analytics-review", analyticsPayload());
        const mode = data.action === "scale" ? "ok" : data.action === "stop" ? "bad" : "warn";
        $("analyticsSummary").innerHTML = [iconPill(statusLabel(data.action || "decision"), mode), iconPill(data.review_window || $("reviewWindow").value, "neutral")].join("");
        setJson("analyticsResult", data);
        showToast(`${t("decisionPrefix")}: ${statusLabel(data.action)}`);
      } catch (error) {
        $("analyticsSummary").innerHTML = iconPill(t("reviewFailed"), "bad");
        setJson("analyticsResult", String(error.message || error));
      }
    });

    $("loadWeakSignal").addEventListener("click", () => setAnalyticsExample("weak"));
    $("loadScaleSignal").addEventListener("click", () => setAnalyticsExample("scale"));
    $("loadLeadExample").addEventListener("click", setLeadExample);
    $("refreshLeads").addEventListener("click", () => refreshLeadList().then(() => showToast(t("leadsRefreshed"))));
    $("refreshOutbox").addEventListener("click", () => refreshOutboxList().then(() => showToast(t("outboxRefreshed"))));

    $("routeSchedulerDraft").addEventListener("click", async () => {
      try {
        const data = await postJson("/workflows/route-scheduler-draft", {
          content_id: $("routeContentId").value.trim(),
          target: $("routeSchedulerTarget").value,
          dry_run: $("routeSchedulerDryRun").checked
        });
        renderRouteResult(data);
        await refreshOutboxList();
        showToast(data.route?.status === "blocked" ? t("routeBlocked") : t("schedulerRoutePrepared"));
      } catch (error) {
        $("routeSummary").innerHTML = iconPill(t("routeFailed"), "bad");
        setJson("routeResult", String(error.message || error));
      }
    });

    $("routeLead").addEventListener("click", async () => {
      try {
        const data = await postJson("/workflows/route-lead", {
          lead_id: $("routeLeadId").value.trim(),
          target: $("routeLeadTarget").value,
          dry_run: $("routeLeadDryRun").checked
        });
        renderRouteResult(data);
        await refreshOutboxList();
        showToast(data.route?.status === "blocked" ? t("leadRouteBlocked") : t("leadRoutePrepared"));
      } catch (error) {
        $("routeSummary").innerHTML = iconPill(t("routeFailed"), "bad");
        setJson("routeResult", String(error.message || error));
      }
    });

    $("leadForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const data = await postJson("/workflows/lead-intake", leadPayload());
        const lead = data.lead || {};
        $("routeLeadId").value = lead.id || $("leadId").value.trim();
        const mode = data.routing_allowed ? "ok" : lead.next_action === "consent_required" ? "bad" : "warn";
        $("leadSummary").innerHTML = [
          iconPill(statusLabel(lead.next_action || "next action"), mode),
          iconPill(`${lead.qualification_score || 0} ${t("scoreUnit")}`, mode),
          iconPill(data.routing_allowed ? t("crmPayloadReady") : t("doNotRoute"), data.routing_allowed ? "ok" : "warn")
        ].join("");
        setJson("leadResult", data);
        await refreshLeadList();
        showToast(data.routing_allowed ? t("leadReady") : t("leadStored"));
      } catch (error) {
        $("leadSummary").innerHTML = iconPill(t("leadRejected"), "bad");
        setJson("leadResult", String(error.message || error));
      }
    });

    $("creativeForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const data = await postJson("/workflows/comfyui-brief", {
          campaign: $("creativeCampaign").value.trim(),
          channel: $("creativeChannel").value,
          format: $("creativeFormat").value.trim(),
          headline: $("headline").value.trim(),
          proof_asset_refs: splitList($("proofAssetRefs").value),
          output_size: $("outputSize").value
        });
        setJson("creativeResult", data);
        showToast(t("creativeBriefCreated"));
      } catch (error) {
        setJson("creativeResult", String(error.message || error));
      }
    });

    if (localStorage.getItem("wamocon-theme") === "dark") {
      document.body.classList.add("theme-dark");
    }
    applyPreset("k1");
    applyUiLanguage(localStorage.getItem("wamocon-ui-language") || "de");
    setScreen((location.hash || "#dashboard").replace("#", "") || "dashboard");
    updatePublishability();
    refreshStatus().catch((error) => setJson("statusResult", String(error.message || error)));
    refreshPhaseStatus().catch((error) => setJson("phaseResult", String(error.message || error)));
    refreshRecent().catch((error) => setJson("intakeResult", String(error.message || error)));
    refreshLeadList().catch((error) => setJson("leadResult", String(error.message || error)));
    refreshOutboxList().catch((error) => setJson("routeResult", String(error.message || error)));
    const initialContentId = new URLSearchParams(window.location.search).get("content_id");
    if (initialContentId) {
      selectContent(initialContentId);
    }
  </script>
</body>
</html>"""
