import { useEffect, useState } from "react";
import DatasetCard from "../components/DatasetCard";
import { Card, EmptyState, ErrorState } from "../components/ui";
import { resolveDatasetIcon } from "../lib/datasetPresentation";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

// Placeholder per design/screens/home/content.md integration notes; replace
// with the real Atlas repository URL once wired up.
const REPOSITORY_URL = "https://github.com/<owner>/<atlas-repo>";
const PORTFOLIO_URL = "https://fabioaguiar.dev/";

type DatasetListing = {
  dataset_slug: string;
  title: string;
  summary: string;
  domain: string;
  visibility: string;
  tags: string[];
  display_title?: string | null;
  display_subtitle?: string | null;
  home_card_icon?: string | null;
  home_card_media_ref?: string | null;
  short_description?: string | null;
  problem_type?: string | null;
};

type DatasetListingResponse = {
  datasets: DatasetListing[];
};

type HomeState =
  | { status: "loading" }
  | { status: "ready"; datasets: DatasetListing[] }
  | { status: "error" };

function GitHubMark() {
  return (
    <svg viewBox="0 0 24 24">
      <path d="M12 3.5a8.5 8.5 0 0 0-2.69 16.56c.43.08.58-.18.58-.41v-1.43c-2.38.52-2.88-1.01-2.88-1.01-.39-.98-.95-1.24-.95-1.24-.77-.53.06-.52.06-.52.85.06 1.31.88 1.31.88.76 1.3 1.98.93 2.47.71.08-.55.3-.93.54-1.15-1.9-.22-3.9-.95-3.9-4.23 0-.93.33-1.69.87-2.29-.09-.22-.38-1.11.08-2.31 0 0 .72-.23 2.36.87a8.07 8.07 0 0 1 4.3 0c1.64-1.1 2.36-.87 2.36-.87.46 1.2.17 2.09.08 2.31.54.6.87 1.36.87 2.29 0 3.29-2.01 4.01-3.92 4.22.31.27.58.81.58 1.64v2.43c0 .23.15.49.59.41A8.5 8.5 0 0 0 12 3.5Z" />
    </svg>
  );
}

export default function HomePage() {
  const [state, setState] = useState<HomeState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();

    fetch(`${apiBaseUrl}/datasets`, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) {
          setState({ status: "error" });
          return;
        }
        return res.json() as Promise<DatasetListingResponse>;
      })
      .then((data) => {
        if (data && Array.isArray(data.datasets)) {
          setState({ status: "ready", datasets: data.datasets });
          return;
        }
        if (data) {
          setState({ status: "error" });
        }
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setState({ status: "error" });
        }
      });

    return () => controller.abort();
  }, []);

  return (
    <>
      <section className="hero" aria-labelledby="home-title">
        <p className="hero__subtitle">DEMONSTRAÇÕES PÚBLICAS DE ANÁLISE PREDITIVA ORIENTADA POR CONTRATOS.</p>
        <h1 id="home-title" className="hero__title">
          Atlas DataFlow<span className="hero__title-mark">.</span>
        </h1>
        <p className="hero__description">
          Coleção de datasets, modelos e demonstrações que seguem contratos de dados bem definidos para garantir
          reprodutibilidade, qualidade e transparência em cada etapa.
        </p>
        <div className="hero__actions" aria-label="Links principais">
          <a className="hero__link hero__link--repo" href={REPOSITORY_URL} target="_blank" rel="noreferrer">
            <span className="hero__link-icon" aria-hidden="true">
              <GitHubMark />
            </span>
            Repositório
            <span aria-hidden="true">↗</span>
          </a>
          <a className="hero__link hero__link--portfolio" href={PORTFOLIO_URL}>
            <span aria-hidden="true">←</span>
            Voltar ao Portfólio
          </a>
        </div>
      </section>

      <section className="featured-datasets" aria-labelledby="featured-title">
        <div className="featured-datasets__heading">
          <h2 id="featured-title">Datasets em destaque</h2>
          <p>
            Os cards abaixo representam os datasets públicos disponíveis hoje e o layout permanece pronto para
            crescer conforme novas análises forem publicadas.
          </p>
        </div>

        {state.status === "loading" && (
          <Card aria-label="Carregando datasets">
            <p>Carregando datasets...</p>
          </Card>
        )}

        {state.status === "error" && (
          <ErrorState title="Datasets indisponíveis" message="Verifique se a API está em execução." />
        )}

        {state.status === "ready" &&
          (state.datasets.length === 0 ? (
            <EmptyState title="Nenhum dataset disponível" message="Os datasets publicados aparecerão aqui." />
          ) : (
            <div className="featured-datasets__grid">
              {state.datasets.map((ds) => (
                <DatasetCard
                  key={ds.dataset_slug}
                  slug={ds.dataset_slug}
                  title={ds.display_title || ds.title || ds.dataset_slug}
                  summary={ds.short_description || ds.display_subtitle || ds.summary}
                  domain={ds.domain}
                  tags={ds.tags}
                  problemType={ds.problem_type ?? undefined}
                  iconOverride={resolveDatasetIcon(ds.home_card_icon, ds.domain, ds.tags)}
                  mediaRef={ds.home_card_media_ref}
                />
              ))}
            </div>
          ))}
      </section>

      <footer className="site-footer">
        Atlas DataFlow é um projeto de <strong className="site-footer__highlight">Fábio Aguiar</strong>.
      </footer>
    </>
  );
}
