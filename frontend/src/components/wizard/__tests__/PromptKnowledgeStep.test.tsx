import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PromptKnowledgeStep } from "@/components/wizard/PromptKnowledgeStep";
import { DEFAULT_FORM, type AgentForm } from "@/lib/wizard-data";
import type { KnowledgeDocumentItem } from "@/lib/api-types";

const useKnowledgeBaseMock = vi.fn();
vi.mock("@/hooks/useKnowledgeBase", () => ({
  useKnowledgeBase: (...args: unknown[]) => useKnowledgeBaseMock(...args),
}));

function makeDoc(overrides: Partial<KnowledgeDocumentItem> = {}): KnowledgeDocumentItem {
  return {
    document_id: "doc-1",
    org_id: "org-1",
    original_filename: "handbook.pdf",
    status: "ready",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function kbState(overrides: Partial<{
  documents: KnowledgeDocumentItem[];
  loading: boolean;
  loadError: string;
  uploading: boolean;
}> = {}) {
  return {
    documents: [] as KnowledgeDocumentItem[],
    loading: false,
    loadError: "",
    uploading: false,
    busyId: null,
    upload: vi.fn(),
    remove: vi.fn(),
    reload: vi.fn(),
    ...overrides,
  };
}

function renderStep(formOverrides: Partial<AgentForm> = {}) {
  const onChange = vi.fn();
  const form: AgentForm = { ...DEFAULT_FORM, ...formOverrides };
  render(
    <PromptKnowledgeStep
      form={form}
      onChange={onChange}
      onOpenLibrary={vi.fn()}
      onNotify={vi.fn()}
    />
  );
  return { onChange, form };
}

describe("PromptKnowledgeStep — knowledge base", () => {
  beforeEach(() => {
    useKnowledgeBaseMock.mockReset();
    useKnowledgeBaseMock.mockReturnValue(kbState());
  });

  it("hides the document panel when kbEnabled is false", () => {
    renderStep({ kbEnabled: false });
    expect(screen.queryByText("Documents")).not.toBeInTheDocument();
  });

  it("shows the document panel and list when kbEnabled is true", () => {
    useKnowledgeBaseMock.mockReturnValue(kbState({ documents: [makeDoc()] }));
    renderStep({ kbEnabled: true });
    expect(screen.getByText("Documents")).toBeInTheDocument();
    expect(screen.getByText("handbook.pdf")).toBeInTheDocument();
  });

  it("toggling the switch calls onChange with kbEnabled", async () => {
    const user = userEvent.setup();
    const { onChange } = renderStep({ kbEnabled: false });

    await user.click(screen.getByRole("switch", { name: /use knowledge base/i }));

    expect(onChange).toHaveBeenCalledWith("kbEnabled", true);
  });

  it("shows the loading state while documents are loading", () => {
    useKnowledgeBaseMock.mockReturnValue(kbState({ loading: true }));
    renderStep({ kbEnabled: true });
    expect(screen.getByText(/getting knowledge base documents/i)).toBeInTheDocument();
  });

  it("shows the load error instead of the list when loading failed", () => {
    useKnowledgeBaseMock.mockReturnValue(kbState({ loadError: "Network error" }));
    renderStep({ kbEnabled: true });
    expect(screen.getByText("Network error")).toBeInTheDocument();
  });

  it("shows the empty state when there are no documents", () => {
    renderStep({ kbEnabled: true });
    expect(screen.getByText(/no documents uploaded yet/i)).toBeInTheDocument();
  });

  it("filters the document list by filename via the search box", async () => {
    const user = userEvent.setup();
    useKnowledgeBaseMock.mockReturnValue(
      kbState({
        documents: [
          makeDoc({ document_id: "doc-1", original_filename: "handbook.pdf" }),
          makeDoc({ document_id: "doc-2", original_filename: "pricing.pdf" }),
        ],
      })
    );
    renderStep({ kbEnabled: true });

    expect(screen.getByText("handbook.pdf")).toBeInTheDocument();
    expect(screen.getByText("pricing.pdf")).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("Search documents…"), "pricing");

    expect(screen.queryByText("handbook.pdf")).not.toBeInTheDocument();
    expect(screen.getByText("pricing.pdf")).toBeInTheDocument();
  });

  it("shows a no-match message when the search filters out every document", async () => {
    const user = userEvent.setup();
    useKnowledgeBaseMock.mockReturnValue(kbState({ documents: [makeDoc()] }));
    renderStep({ kbEnabled: true });

    await user.type(screen.getByPlaceholderText("Search documents…"), "nonexistent");

    expect(screen.getByText(/no documents match/i)).toBeInTheDocument();
  });

  it("checks a document already present in form.kbDocs", () => {
    useKnowledgeBaseMock.mockReturnValue(kbState({ documents: [makeDoc({ document_id: "doc-1" })] }));
    renderStep({ kbEnabled: true, kbDocs: ["doc-1"] });

    const checkbox = screen.getByRole("checkbox", { name: /handbook\.pdf/i });
    expect(checkbox).toBeChecked();
  });

  it("adds the document id to kbDocs when an unchecked ready document is clicked", async () => {
    const user = userEvent.setup();
    useKnowledgeBaseMock.mockReturnValue(kbState({ documents: [makeDoc({ document_id: "doc-1" })] }));
    const { onChange } = renderStep({ kbEnabled: true, kbDocs: [] });

    const checkbox = screen.getByRole("checkbox", { name: /handbook\.pdf/i });
    await user.click(checkbox);

    expect(onChange).toHaveBeenCalledWith("kbDocs", ["doc-1"]);
  });

  it("removes the document id from kbDocs when a checked document is clicked", async () => {
    const user = userEvent.setup();
    useKnowledgeBaseMock.mockReturnValue(kbState({ documents: [makeDoc({ document_id: "doc-1" })] }));
    const { onChange } = renderStep({ kbEnabled: true, kbDocs: ["doc-1", "doc-2"] });

    const checkbox = screen.getByRole("checkbox", { name: /handbook\.pdf/i });
    await user.click(checkbox);

    expect(onChange).toHaveBeenCalledWith("kbDocs", ["doc-2"]);
  });

  it("disables the checkbox and shows a status label for a processing document", () => {
    useKnowledgeBaseMock.mockReturnValue(
      kbState({ documents: [makeDoc({ document_id: "doc-1", status: "processing" })] })
    );
    renderStep({ kbEnabled: true });

    const checkbox = screen.getByRole("checkbox", { name: /handbook\.pdf/i });
    expect(checkbox).toBeDisabled();
    expect(screen.getByText("processing…")).toBeInTheDocument();
  });

  it("disables the checkbox and shows a status label for a failed document", () => {
    useKnowledgeBaseMock.mockReturnValue(
      kbState({ documents: [makeDoc({ document_id: "doc-1", status: "failed" })] })
    );
    renderStep({ kbEnabled: true });

    const checkbox = screen.getByRole("checkbox", { name: /handbook\.pdf/i });
    expect(checkbox).toBeDisabled();
    expect(screen.getByText("failed")).toBeInTheDocument();
  });

  it("does not call onChange when clicking a disabled (non-ready) document", async () => {
    const user = userEvent.setup();
    useKnowledgeBaseMock.mockReturnValue(
      kbState({ documents: [makeDoc({ document_id: "doc-1", status: "processing" })] })
    );
    const { onChange } = renderStep({ kbEnabled: true, kbDocs: [] });

    const checkbox = screen.getByRole("checkbox", { name: /handbook\.pdf/i });
    await user.click(checkbox);

    expect(onChange).not.toHaveBeenCalledWith("kbDocs", expect.anything());
  });

  it("opens the upload dialog when 'Upload knowledge base' is clicked", async () => {
    const user = userEvent.setup();
    renderStep({ kbEnabled: true });

    expect(screen.queryByText(/drag/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /upload knowledge base/i }));

    // Dialog only renders its contents once open={true} — presence of any
    // dialog-only chrome confirms it mounted.
    expect(document.querySelector('[role="dialog"], .fixed')).toBeTruthy();
  });
});
