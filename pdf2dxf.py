#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import division

import argparse
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from typing import Iterator, Tuple
from pathlib import Path

from dxfwrite import DXFEngine as dxf
from lxml import etree

import importlib
svg = importlib.import_module("svg")
import svg

HERE = os.path.dirname(__file__)

logging.basicConfig(level=logging.DEBUG if __debug__ else logging.INFO)
log = logging.getLogger(__name__)

svg_namespace = {'svg': 'http://www.w3.org/2000/svg'}
alto_namespace = {'alto': "http://www.loc.gov/standards/alto/v3/alto.xsd"}


@contextmanager
def chdir(path):
    curdir = os.getcwd()
    os.chdir(path)
    yield
    os.chdir(curdir)


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert vectorial graphics from a PDF file to an SVG file")

    def abspath(apath):
        return Path(apath).expanduser().absolute()

    def existing_file(apath):
        p = abspath(apath)
        if not p.exists():
            parser.error(f"Missing PDF file {p}")
        return p

    parser.add_argument("pdf", type=existing_file)
    parser.add_argument("dxf", type=abspath)
    return parser.parse_args()


PagesAndSizes = Iterator[Tuple[bytes, Tuple[float, float]]]


def iter_pages_and_sizes(alto_file: str) -> PagesAndSizes:
    log.debug(f"Parsing svg {alto_file}")
    alto_xml = etree.parse(alto_file)
    for page in alto_xml.xpath('//alto:Page[.//alto:Illustration]', namespaces=alto_namespace):
        log.debug(f"... page {page}")
        w, h = page.get("WIDTH"), page.get("HEIGHT")
        illustration = page.xpath(".//alto:Illustration", namespaces=alto_namespace).pop()
        svg_path = illustration.get("FILEID")
        log.debug(f"w: {w}, h: {h}, fileid: {svg_path}")
        if w and h and svg_path:
            try:
                log.debug(f"Yielding {svg_path}")
                yield svg_path, (float(w), float(h))
            except ValueError:
                log.exception("Invalid sizes")


def iter_svg_from_pdf(source: str) -> PagesAndSizes:
    """Return an iterator on svn paths and page sizes (w, h).
    WARNING: the paths are valid only for the lifetime of the iterator, because the
    temporary folder they are in is deleted after the last iteration."""
    log.debug(f"Iterating svgs from {source}")
    exe = 'pdfalto.exe' if sys.platform.startswith('win32') else 'pdfalto'
    if hasattr(sys, "frozen"):
        pdfalto = os.path.abspath(os.path.join(sys._MEIPASS, exe))
    else:
        pdfalto = os.path.abspath(os.path.join(HERE, f'../../lib/pdfalto/{sys.platform}', exe))
    tmpdir = tempfile.mkdtemp('.pdfimport')  # TODO: may use tempfile.TemporaryDirectory()
    with chdir(tmpdir):
        log.debug(f"In {tmpdir}...")
        args = [pdfalto, str(source), 'out.xml']
        log.debug(f"Spawning {' '.join(args)}")
        subprocess.check_call(args)
        yield from iter_pages_and_sizes('out.xml')
    log.debug(f"Removing {tmpdir}: {os.listdir(tmpdir)}")
    shutil.rmtree(tmpdir, ignore_errors=True)


def convert(source: str, dest: str):
    log.debug(f"Converting {source} in {dest}")
    image = svg.parse(source)
    bmim, bmax = image.bbox()
    max_y = bmax.y
    drawing = dxf.drawing(dest)

    def flipped_y(p):
        # pdf sizes @ 72 px/in -> mm
        return (p.x / 72 * 25.4, (max_y - p.y) / 72 * 25.4)

    for part in image.flatten():
        if hasattr(part, 'segments'):
            for segment in part.segments():
                drawing.add(dxf.polyline([flipped_y(p) for p in segment]))
        else:
            log.debug(f"Unsupported SVG element {type(part).__name__}")

    drawing.save()


def run():
    args = get_args()
    for c, (svg_path, size_wh) in enumerate(iter_svg_from_pdf(args.pdf)):
        convert(svg_path, args.dxf)
        if c > 0:
            log.debug("Only the first page is currently exported")
            break


if __name__ == "__main__":
    run()
