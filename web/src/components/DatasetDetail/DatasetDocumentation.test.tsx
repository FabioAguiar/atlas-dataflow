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

// Project Spec S0199: bounded external GitHub raw-image rendering. Only a
// Markdown `img` whose `src` is an exact, well-formed
// `https://raw.githubusercontent.com/owner/repository/ref/path.ext`
// reference renders; every other source is omitted without breaking the
// rest of Documentation rendering. Local Documentation media storage
// (S0197) is retired -- this renderer never fetches, proxies, or knows
// about a dataset slug.
describe("DatasetDocumentation bounded external image rendering (Project Spec S0199)", () => {
  const safeSrc = "https://raw.githubusercontent.com/FabioAguiar/dataset-study-telco-customer-churn/main/docs/images/churn_target_class_distribution.png";

  it("renders a raw.githubusercontent.com PNG and preserves alt text, lazy loading, and async decoding", () => {
    const { container } = render(
      <DatasetDocumentation content={`![Churn overview chart](${safeSrc})`} />,
    );

    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    expect(img).toHaveAttribute("src", safeSrc);
    expect(img).toHaveAttribute("alt", "Churn overview chart");
    expect(img).toHaveAttribute("loading", "lazy");
    expect(img).toHaveAttribute("decoding", "async");
  });

  it.each(["png", "jpg", "jpeg", "webp", "avif"])("accepts a raw GitHub %s image reference", (extension) => {
    const src = `https://raw.githubusercontent.com/owner/repository/main/docs/images/chart.${extension}`;
    const { container } = render(<DatasetDocumentation content={`![alt](${src})`} />);
    expect(container.querySelector("img")).toHaveAttribute("src", src);
  });

  it("accepts a commit-SHA ref path", () => {
    const src = "https://raw.githubusercontent.com/owner/repository/0123456789abcdef0123456789abcdef01234567/docs/images/chart.webp";
    const { container } = render(<DatasetDocumentation content={`![alt](${src})`} />);
    expect(container.querySelector("img")).toHaveAttribute("src", src);
  });

  it("omits an unsafe or foreign image source without breaking the rest of Documentation rendering", () => {
    const unsafeCases = [
      "https://github.com/FabioAguiar/dataset-study-telco-customer-churn/blob/main/docs/images/chart.png",
      "https://example.org/chart.png",
      "http://raw.githubusercontent.com/owner/repo/main/chart.png",
      "https://raw.githubusercontent.com.evil.example/owner/repo/main/chart.png",
      "//raw.githubusercontent.com/owner/repo/main/chart.png",
      "data:image/png;base64,aGVsbG8=",
      "javascript:alert(1)",
      "file:///tmp/chart.png",
      "blob:https://example.org/00000000-0000-0000-0000-000000000000",
      "/media/documentation/example-dataset/0123456789abcdef0123456789abcdef.png",
      "https://user:pass@raw.githubusercontent.com/owner/repo/main/chart.png",
      "https://raw.githubusercontent.com:8443/owner/repo/main/chart.png",
      "https://raw.githubusercontent.com/owner/repo/main/chart.png?x=1",
      "https://raw.githubusercontent.com/owner/repo/main/chart.png#fragment",
      "https://raw.githubusercontent.com/owner/repo/main/chart.svg",
      "https://raw.githubusercontent.com/owner/repo/chart.png",
    ];

    for (const unsafeSrc of unsafeCases) {
      const { container, unmount } = render(
        <DatasetDocumentation content={`Before text.\n\n![alt](${unsafeSrc})\n\nAfter text.`} />,
      );
      expect(container.querySelector("img")).toBeNull();
      expect(screen.getByText("Before text.")).toBeInTheDocument();
      expect(screen.getByText("After text.")).toBeInTheDocument();
      unmount();
    }
  });

  it("does not treat raw HTML as active markup alongside a valid image", () => {
    render(
      <DatasetDocumentation content={`![alt](${safeSrc})\n\nBefore <strong id="raw">raw html</strong> after`} />,
    );

    expect(document.getElementById("raw")).toBeNull();
    expect(screen.getByText(/raw html/)).toBeInTheDocument();
  });

  it("still renders headings, lists, tables, and links alongside a valid image", () => {
    render(
      <DatasetDocumentation
        content={`# Title\n\n![alt](${safeSrc})\n\n- Item one\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n[Link](https://example.org)`}
      />,
    );

    expect(screen.getByRole("heading", { level: 1, name: "Title" })).toBeInTheDocument();
    expect(screen.getByText("Item one").closest("ul")).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Link" })).toBeInTheDocument();
  });
});
