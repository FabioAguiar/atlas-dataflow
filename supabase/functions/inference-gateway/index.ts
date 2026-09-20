// M52-04: Deno entrypoint for the inference gateway. Wiring only; every
// decision lives in handler.ts.
import { createClient } from "npm:@supabase/supabase-js@2";
import { createRemoteJWKSet, jwtVerify } from "npm:jose@5";
import { handleRequest, resolveVerifierConfig } from "./handler.ts";

const supabaseUrl = (Deno.env.get("SUPABASE_URL") ?? "").trim().replace(/\/+$/, "");
const serviceRoleKey = (Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "").trim();
const platformConfigured = supabaseUrl.length > 0 && serviceRoleKey.length > 0;

// SUPABASE_URL is the internal runtime/API URL (reservation client only).
// The expected issuer and JWKS address come from optional explicit config and
// fall back to SUPABASE_URL-derived values (hosted default).
const verifier = platformConfigured
  ? resolveVerifierConfig({
    supabaseUrl,
    issuerOverride: Deno.env.get("ATLAS_SUPABASE_JWT_ISSUER"),
    jwksUrlOverride: Deno.env.get("ATLAS_SUPABASE_JWKS_URL"),
  })
  : null;

const jwks = verifier !== null
  ? createRemoteJWKSet(new URL(verifier.jwksUrl), { timeoutDuration: 5000 })
  : null;

// service_role client used only for the reservation RPC; the visitor token is
// never used for database access.
const reservationClient = platformConfigured
  ? createClient(supabaseUrl, serviceRoleKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  })
  : null;

Deno.serve((request: Request) =>
  handleRequest(request, {
    config: {
      atlasToken: Deno.env.get("ATLAS_GATEWAY_TOKEN"),
      atlasBaseUrl: Deno.env.get("ATLAS_GATEWAY_BASE_URL"),
      allowPrivateHttp: Deno.env.get("ATLAS_GATEWAY_ALLOW_PRIVATE_HTTP"),
      allowedOrigins: Deno.env.get("ATLAS_GATEWAY_ALLOWED_ORIGINS"),
      platformConfigured,
    },
    verifyJwt: async (token: string) => {
      if (jwks === null || verifier === null) throw new Error("verifier unavailable");
      const { payload } = await jwtVerify(token, jwks, {
        issuer: verifier.issuer,
        audience: "authenticated",
        algorithms: ["ES256", "RS256", "EdDSA"],
      });
      return payload as Record<string, unknown>;
    },
    reserve: async (subjectId: string, datasetSlug: string) => {
      if (reservationClient === null) throw new Error("reservation unavailable");
      const { data, error } = await reservationClient.rpc("reserve_inference_usage", {
        p_subject_id: subjectId,
        p_dataset_slug: datasetSlug,
      });
      if (error) throw new Error("reservation failed");
      return data;
    },
    forward: (url: string, init: RequestInit) => fetch(url, init),
    log: (line: string) => console.log(line),
  })
);
