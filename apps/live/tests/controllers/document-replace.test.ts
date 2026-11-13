/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { describe, expect, it, vi } from "vitest";
import * as Y from "yjs";
import {
  getAllDocumentFormatsFromDocumentEditorBinaryData,
  getBinaryDataFromDocumentEditorHTMLString,
} from "@plane/editor";

vi.hoisted(() => {
  process.env.API_BASE_URL = "http://api.test";
  process.env.LIVE_SERVER_SECRET_KEY = "unit-test-live-secret";
});

import { replaceFragment } from "@/controllers/document-replace.controller";

const html = (doc: Y.Doc) =>
  getAllDocumentFormatsFromDocumentEditorBinaryData(Y.encodeStateAsUpdate(doc), true).contentHTML;

const docWith = (body: string, title?: string) => {
  const doc = new Y.Doc();
  Y.applyUpdate(doc, getBinaryDataFromDocumentEditorHTMLString(body, title));
  return doc;
};

describe("replaceFragment", () => {
  it("replaces the body instead of appending to it", () => {
    const doc = docWith("<p>old body</p>", "Title");
    replaceFragment(doc, "default", getBinaryDataFromDocumentEditorHTMLString("<p>new body</p>"));
    const out = html(doc);
    expect(out).toContain("new body");
    expect(out).not.toContain("old body");
  });

  it("reaches an open editor without duplicating content when it syncs back", () => {
    const server = docWith("<p>shared text</p>");
    // An editor that has the document open holds its own replica.
    const editor = new Y.Doc();
    Y.applyUpdate(editor, Y.encodeStateAsUpdate(server));

    const before = Y.encodeStateVector(server);
    replaceFragment(server, "default", getBinaryDataFromDocumentEditorHTMLString("<p>from the API</p>"));
    // The editor receives only the change, then sends its whole state back (a reconnect).
    Y.applyUpdate(editor, Y.encodeStateAsUpdate(server, Y.encodeStateVectorFromUpdate(Y.encodeStateAsUpdate(editor))));
    Y.applyUpdate(server, Y.encodeStateAsUpdate(editor, before));

    for (const doc of [server, editor]) {
      const out = html(doc);
      expect(out).toContain("from the API");
      expect(out).not.toContain("shared text");
      expect(out.split("from the API").length).toBe(2);
    }
  });
});
