/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Hocuspocus } from "@hocuspocus/server";
import { TiptapTransformer } from "@hocuspocus/transformer";
import type { AnyExtension, JSONContent } from "@tiptap/core";
import type { Request, Response } from "express";
import * as Y from "yjs";
import { z } from "zod";
// plane imports
import { Controller, Middleware, Post } from "@plane/decorators";
import {
  TITLE_EDITOR_EXTENSIONS,
  generateTitleProsemirrorJson,
  getBinaryDataFromDocumentEditorHTMLString,
} from "@plane/editor";
import { logger } from "@plane/logger";
import { requireSecretKey } from "@/lib/auth-middleware";

const replaceSchema = z
  .object({
    document_name: z.string().uuid(),
    description_html: z.string().optional(),
    name: z.string().optional(),
  })
  .refine((body) => body.description_html !== undefined || body.name !== undefined, {
    message: "Pass description_html, name, or both",
  });

/** Empty a root fragment, then merge the replacement content into it. */
export const replaceFragment = (document: Y.Doc, fragmentName: string, replacement: Uint8Array) => {
  const fragment = document.getXmlFragment(fragmentName);
  fragment.delete(0, fragment.length);
  Y.applyUpdate(document, replacement);
};

/**
 * Lets the API replace the content of a page that someone has open.
 *
 * Writing the database underneath an open document does not work: the next
 * save from the editors overwrites it, and a client that reconnects merges its
 * own copy back in. The change is applied inside the loaded document instead,
 * so every editor receives it and the regular save persists it. When the
 * document is not loaded here, the answer is `applied: false` and the API
 * writes the database itself.
 *
 * Only documents loaded on this instance are seen: run a single live replica,
 * or a page open on another replica can overwrite the API's direct write.
 */
@Controller("/documents")
export class DocumentReplaceController {
  [key: string]: unknown;
  private readonly hocusPocusServer: Hocuspocus;

  constructor(hocusPocusServer: Hocuspocus) {
    this.hocusPocusServer = hocusPocusServer;
  }

  @Post("/replace")
  @Middleware(requireSecretKey)
  async replace(req: Request, res: Response) {
    const parsed = replaceSchema.safeParse(req.body);
    if (!parsed.success) {
      return res.status(400).json({ message: "Validation error", issues: parsed.error.issues });
    }
    const { document_name: documentName, description_html: html, name } = parsed.data;

    const loaded = this.hocusPocusServer.documents.get(documentName);
    if (!loaded) return res.status(200).json({ applied: false });

    // Saves run with the context of a connection; borrow an editor's so the
    // store goes through the same permission checks as their own edits.
    const editor = loaded.getConnections().find((connection) => !connection.readOnly);
    if (!editor) {
      // Loaded but everyone has left: the pending save would overwrite a
      // direct database write, so ask the caller to retry once it settles.
      return res.status(409).json({ message: "The document is closing; retry shortly." });
    }

    try {
      const connection = await this.hocusPocusServer.openDirectConnection(documentName, editor.context);
      try {
        await connection.transact((document) => {
          if (html !== undefined) {
            replaceFragment(document, "default", getBinaryDataFromDocumentEditorHTMLString(html || "<p></p>"));
          }
          if (name !== undefined) {
            const titleJson = (generateTitleProsemirrorJson as (text: string) => JSONContent)(name);
            const title = TiptapTransformer.toYdoc(titleJson, "title", TITLE_EDITOR_EXTENSIONS as AnyExtension[]);
            replaceFragment(document, "title", Y.encodeStateAsUpdate(title));
          }
        });
      } finally {
        await connection.disconnect();
      }
      return res.status(200).json({ applied: true });
    } catch (error) {
      logger.error("DOCUMENT_REPLACE_CONTROLLER: failed to apply content", error);
      return res.status(500).json({ message: "Internal server error." });
    }
  }
}
