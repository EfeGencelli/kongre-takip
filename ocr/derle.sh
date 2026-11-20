#!/bin/bash
# Başkanın taranmış işlem raporlarını okuyan aracı derler (yalnızca macOS: PDFKit + Vision).
set -e
cd "$(dirname "$0")/.."
mkdir -p bin
xcrun swiftc -O ocr/ocr.swift -o bin/kongre-ocr -framework PDFKit -framework Vision -framework AppKit
echo "✓ bin/kongre-ocr hazır"
