/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { Globe2, Lock } from "lucide-react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { EModalPosition, EModalWidth, Input, ModalCore } from "@plane/ui";
import { cn } from "@plane/utils";
// hooks
import { EPageStoreType, usePageStore } from "@/hooks/store";
// plane web
import type { TWikiCollection } from "@/plane-web/types/wiki";

type Props = {
  isOpen: boolean;
  onClose: () => void;
  /** Edit this collection; create a new one when absent. */
  collection?: TWikiCollection;
};

export const CollectionFormModal = observer(function CollectionFormModal(props: Props) {
  const { isOpen, onClose, collection } = props;
  const { workspaceSlug } = useParams();
  const { t } = useTranslation();
  const { createCollection, updateCollection } = usePageStore(EPageStoreType.WORKSPACE);
  const [name, setName] = useState("");
  const [access, setAccess] = useState<0 | 1>(0);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setName(collection?.name ?? "");
    setAccess(collection?.access ?? 0);
  }, [isOpen, collection]);

  const trimmed = name.trim();
  const error = !trimmed
    ? t("wiki_collections.form.name_required")
    : trimmed.length > 255
      ? t("wiki_collections.form.name_max_length")
      : undefined;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (error || !workspaceSlug) return;
    setIsSubmitting(true);
    try {
      if (collection) {
        await updateCollection(workspaceSlug.toString(), collection.id, { name: trimmed });
        setToast({
          type: TOAST_TYPE.SUCCESS,
          title: t("toast.success"),
          message: t("wiki_collections.toasts.renamed"),
        });
      } else {
        await createCollection(workspaceSlug.toString(), { name: trimmed, access });
        setToast({
          type: TOAST_TYPE.SUCCESS,
          title: t("toast.success"),
          message: t("wiki_collections.toasts.created"),
        });
      }
      onClose();
    } catch {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: t("toast.error"),
        message: collection ? t("wiki_collections.toasts.rename_error") : t("wiki_collections.toasts.create_error"),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const accessOptions = [
    {
      value: 0 as const,
      icon: Globe2,
      label: t("common.access.public"),
      hint: t("workspace_wiki.collection.public_hint"),
    },
    {
      value: 1 as const,
      icon: Lock,
      label: t("common.access.private"),
      hint: t("workspace_wiki.collection.private_hint"),
    },
  ];

  return (
    <ModalCore isOpen={isOpen} handleClose={onClose} position={EModalPosition.TOP} width={EModalWidth.LG}>
      <form onSubmit={handleSubmit} className="space-y-4 p-5">
        <h3 className="text-18 font-medium text-primary">
          {collection ? t("wiki_collections.edit_modal.title") : t("wiki_collections.create_modal.title")}
        </h3>
        <Input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={
            collection
              ? t("wiki_collections.form.name_placeholder_edit")
              : t("wiki_collections.form.name_placeholder_create")
          }
          className="w-full"
          hasError={!!name && !!error}
        />
        {!collection && (
          <div className="grid grid-cols-2 gap-2">
            {accessOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setAccess(option.value)}
                className={cn(
                  "flex flex-col items-start gap-1 rounded-md border px-3 py-2 text-left",
                  access === option.value ? "border-accent-strong bg-layer-transparent-active" : "border-subtle"
                )}
              >
                <span className="flex items-center gap-1.5 text-13 font-medium text-primary">
                  <option.icon className="size-3.5" />
                  {option.label}
                </span>
                <span className="text-12 text-tertiary">{option.hint}</span>
              </button>
            ))}
          </div>
        )}
        {collection && <p className="text-12 text-tertiary">{t("workspace_wiki.collection.access_fixed")}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" size="sm" type="submit" loading={isSubmitting} disabled={!!error || isSubmitting}>
            {collection ? t("common.actions.edit") : t("wiki_collections.create_modal.submit")}
          </Button>
        </div>
      </form>
    </ModalCore>
  );
});
