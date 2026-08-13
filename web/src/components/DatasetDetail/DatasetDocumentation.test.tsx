import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import DatasetDocumentation from "./DatasetDocumentation";

afterEach(() => {
  cleanup();
});

describe("DatasetDocumentation", () => {
  it("renders headings, paragraphs, and emphasis", () => {
    render(<DatasetDocumentation content={"# Title\n\nA **bold** and *italic* paragraph."} />);

    expect(screen.getByRole("heading", { level: 1, name: "Title" })).toBeInTheDocument();
    expect(screen.getByText("bold")).toBeInTheDocument();
    expect(screen.getByText("bold").tagName).toBe("STRONG");
    expect(screen.getByText("italic")).toBeInTheDocument();
    expect(screen.getByText("italic").tagName).toBe("EM");
  });

  it("renders unordered and ordered lists", () => {
    render(
      <DatasetDocumentation
        content={"- First\n- Second\n\n1. One\n2. Two"}
      />,
    );

    expect(screen.getByText("First").closest("ul")).toBeInTheDocument();
    expect(screen.getByText("Second").closest("ul")).toBeInTheDocument();
    expect(screen.getByText("One").closest("ol")).toBeInTheDocument();
    expect(screen.getByText("Two").closest("ol")).toBeInTheDocument();
  });

  it("renders blockquotes and code", () => {
    render(
      <DatasetDocumentation
        content={"> A quoted line\n\n`inline code`\n\n```\nfenced code block\n```"}
      />,
    );

    expect(screen.getByText("A quoted line").closest("blockquote")).toBeInTheDocument();
    expect(screen.getByText("inline code").tagName).toBe("CODE");
    expect(screen.getByText("fenced code block").closest("pre")).toBeInTheDocument();
  });

  it("renders GFM tables as semantic table/thead/tbody markup", () => {
    render(
      <DatasetDocumentation
        content={"| Metric | Value |\n| --- | --- |\n| Accuracy | 0.91 |"}
      />,
    );

    const table = screen.getByRole("table");
    expect(table.querySelector("thead")).toBeInTheDocument();
    expect(table.querySelector("tbody")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Metric" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Accuracy" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "0.91" })).toBeInTheDocument();
  });

  it("renders links only under the bounded safe-URL policy", () => {
    render(
      <DatasetDocumentation
        content={"[Safe link](https://example.org/docs) and [dangerous link](javascript:alert(1))"}
      />,
    );

    const safeLink = screen.getByRole("link", { name: "Safe link" });
    expect(safeLink).toHaveAttribute("href", "https://example.org/docs");

    const dangerousLink = screen.getByText("dangerous link").closest("a");
    expect(dangerousLink).not.toBeNull();
    const dangerousHref = dangerousLink?.getAttribute("href") ?? "";
    expect(dangerousHref).not.toContain("javascript:");
  });

  it("does not execute raw HTML as active markup", () => {
    render(<DatasetDocumentation content={"Before <strong id=\"raw\">raw html</strong> after"} />);

    // Raw HTML in the Markdown source is never parsed into DOM elements
    // (no rehype-raw plugin is registered) -- it is inert text content.
    expect(document.getElementById("raw")).toBeNull();
    expect(screen.getByText(/raw html/)).toBeInTheDocument();
  });

  it("does not render an img element for Markdown image syntax", () => {
    const { container } = render(
      <DatasetDocumentation content={"![alt text](https://example.org/pic.png)"} />,
    );

    expect(container.querySelector("img")).toBeNull();
  });

  it("renders the bounded empty state when content is blank", () => {
    render(<DatasetDocumentation content={""} />);
    expect(screen.getByText("No documentation has been published yet.")).toBeInTheDocument();
  });

  it("renders the bounded empty state when content is whitespace-only", () => {
    render(<DatasetDocumentation content={"   \n\n  "} />);
    expect(screen.getByText("No documentation has been published yet.")).toBeInTheDocument();
  });

  it("renders the bounded empty state when content is absent", () => {
    render(<DatasetDocumentation />);
    expect(screen.getByText("No documentation has been published yet.")).toBeInTheDocument();
  });

  it("accepts a bounded {format, content} documentation payload", () => {
    render(
      <DatasetDocumentation
        content={{ format: "markdown", content: "# Payload heading" }}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Payload heading" })).toBeInTheDocument();
  });
});

// Project Spec S0197: bounded Documentation image rendering. Only a
// Markdown `img` whose `src` exactly matches the current dataset's
// generated Documentation media namespace renders; every other source is
// omitted without breaking the rest of Documentation rendering.
describe("DatasetDocumentation bounded image rendering (Project Spec S0197)", () => {
  const datasetSlug = "example-dataset";
  const generatedFilename = "0123456789abcdef0123456789abcdef.png";
  const safeSrc = `/media/documentation/${datasetSlug}/${generatedFilename}`;

  it("renders a same-dataset Documentation media image and preserves alt text", () => {
    const { container } = render(
      <DatasetDocumentation content={`![Churn overview chart](${safeSrc})`} datasetSlug={datasetSlug} />,
    );

    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    expect(img).toHaveAttribute("src", safeSrc);
    expect(img).toHaveAttribute("alt", "Churn overview chart");
    expect(img).toHaveAttribute("loading", "lazy");
    expect(img).toHaveAttribute("decoding", "async");
  });

  it.each(["png", "jpg", "webp", "avif"])("accepts a generated %s Documentation media reference", (extension) => {
    const src = `/media/documentation/${datasetSlug}/0123456789abcdef0123456789abcdef.${extension}`;
    const { container } = render(<DatasetDocumentation content={`![alt](${src})`} datasetSlug={datasetSlug} />);
    expect(container.querySelector("img")).toHaveAttribute("src", src);
  });

  it("omits an unsafe or foreign image source without breaking the rest of Documentation rendering", () => {
    const unsafeCases = [
      `/media/documentation/other-dataset/${generatedFilename}`,
      "/media/home-cards/0123456789abcdef0123456789abcdef.png",
      "https://example.org/pic.png",
      "http://example.org/pic.png",
      "//example.org/pic.png",
      "data:image/png;base64,aGVsbG8=",
      "javascript:alert(1)",
      "file:///etc/passwd",
      "blob:https://example.org/00000000-0000-0000-0000-000000000000",
      `/media/documentation/../${datasetSlug}/${generatedFilename}`,
      `/media/documentation/${datasetSlug}/../${generatedFilename}`,
      `${safeSrc}?x=1`,
      `${safeSrc}#fragment`,
    ];

    for (const unsafeSrc of unsafeCases) {
      const { container, unmount } = render(
        <DatasetDocumentation
          content={`Before text.\n\n![alt](${unsafeSrc})\n\nAfter text.`}
          datasetSlug={datasetSlug}
        />,
      );
      expect(container.querySelector("img")).toBeNull();
      expect(screen.getByText("Before text.")).toBeInTheDocument();
      expect(screen.getByText("After text.")).toBeInTheDocument();
      unmount();
    }
  });

  it("does not render an image when no datasetSlug is provided", () => {
    const { container } = render(<DatasetDocumentation content={`![alt](${safeSrc})`} />);
    expect(container.querySelector("img")).toBeNull();
  });

  it("does not treat raw HTML as active markup alongside a valid image", () => {
    render(
      <DatasetDocumentation
        content={`![alt](${safeSrc})\n\nBefore <strong id="raw">raw html</strong> after`}
        datasetSlug={datasetSlug}
      />,
    );

    expect(document.getElementById("raw")).toBeNull();
    expect(screen.getByText(/raw html/)).toBeInTheDocument();
  });

  it("still renders headings, lists, tables, and links alongside a valid image", () => {
    render(
      <DatasetDocumentation
        content={`# Title\n\n![alt](${safeSrc})\n\n- Item one\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n[Link](https://example.org)`}
        datasetSlug={datasetSlug}
      />,
    );

    expect(screen.getByRole("heading", { level: 1, name: "Title" })).toBeInTheDocument();
    expect(screen.getByText("Item one").closest("ul")).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Link" })).toBeInTheDocument();
  });
});
