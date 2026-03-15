export interface Vertrag {
  id: string;
  dateiname: string;
  status: string;
  erstellt_am: string;
  aktualisiert_am: string;
  volltext?: string | null;
}

export interface Analyse {
  id: string;
  vertrag_id: string;
  status: string;
  aktueller_pass: string | null;
  fortschritt: number;
  gestartet_am: string;
  beendet_am: string | null;
  fehler: string | null;
  auswertung: Record<string, unknown> | null;
}

export interface AnalyseAuswertung {
  analyse_id: string;
  status: string;
  pipeline_auswertung: Record<string, unknown> | null;
  fundstellen_gesamt: number;
  quellen_verteilung_final: Record<string, number>;
  kategorien_final: Record<string, number>;
  risikostufen_final: Record<string, number>;
  fundstellen_detail: Array<{
    id: string;
    kurzbeschreibung: string;
    kategorie: string;
    risikostufe: string;
    quelle_pass: string;
    segment_ids: string[];
    zusammenfuehrung: Record<string, unknown> | null;
  }>;
}

export interface FundstelleDetail {
  seite: number | null;
  seite_unsicher: boolean;
  ueberschrift: string | null;
  kontext: string | null;
  kontext_start: number | null;
  kontext_ende: number | null;
  segment_ids: string[];
  absatz_referenzen: string[];
  risiko_detail: string;
  alternativformulierung: string;
  bieterfrage: string;
  verhandlungsargumente: string;
  position_im_text: number;
}

export interface Fundstelle {
  id: string;
  analyse_id: string;
  vertrag_id: string;
  textstelle: string;
  kategorie: string;
  risikostufe: string;
  kurzbeschreibung: string;
  erklaerung: string | null;
  empfehlung: string | null;
  quelle_pass: string | null;
  pruef_status: string;
  pruef_kommentar: string | null;
  erstellt_am: string;
  detail: FundstelleDetail | null;
  zusammenfuehrung: Record<string, unknown> | null;
  // Paragraph-level evidence fields
  scope_type: string | null;
  scope_text: string | null;
  trigger_spans: string[] | null;
  evidence_heading_path: string | null;
  evidence_page_from: number | null;
  evidence_page_to: number | null;
}

export interface FundstellenGruppe {
  gruppe_id: string;
  titel: string;
  kategorie: string;
  risikostufe: string;
  zusammenfassung: string;
  anzahl: number;
  fundstellen_ids: string[];
  fundstellen: Fundstelle[];
  themen_familie: string | null;
}

export interface GruppiertesErgebnis {
  gruppen: FundstellenGruppe[];
  debug: {
    vorher: number;
    nachher: number;
    reduktion_prozent: number;
    gruppen_details: Array<Record<string, unknown>>;
  };
}

export interface RisikoThema {
  id: string;
  analyse_id: string;
  vertrag_id: string;
  titel: string;
  kategorie: string;
  risikostufe: string;
  beschreibung: string;
  sortierung: number;
  erstellt_am: string;
  fundstellen: Fundstelle[];
  anzahl: number;
}

export interface ClusteringDebugWarnung {
  typ: string;
  thema?: string;
  nachricht: string;
  fundstelle_id?: string;
  anzahl_themen?: number;
  thema_a?: string;
  thema_b?: string;
  aehnlichkeit?: number;
}

export interface ClusteringDebugThema {
  id: string;
  titel: string;
  kategorie: string;
  risikostufe: string;
  anzahl_evidence: number;
  fundstellen: Array<{
    id: string;
    kurzbeschreibung: string;
    kategorie: string;
    risikostufe: string;
  }>;
}

export interface ClusteringDebug {
  themen: ClusteringDebugThema[];
  metriken: {
    anzahl_einzelfindings: number;
    anzahl_risikothemen: number;
    durchschnittliche_fundstellen_pro_thema: number;
    anzahl_themen_ohne_evidence: number;
    anzahl_evidence_mehrfach_zugeordnet: number;
    anzahl_themen_mit_nur_1_fundstelle: number;
  };
  warnungen: ClusteringDebugWarnung[];
  aehnliche_themen: Array<{
    thema_a: string;
    thema_b: string;
    aehnlichkeit: number;
  }>;
}

// --- Final Editorial Pass types ---

export interface FinalesThemaFundstelle {
  id: string;
  kurzbeschreibung: string;
  kategorie: string;
  risikostufe: string;
  textstelle: string;
  pruef_status: string;
  ist_primaer: boolean;
  // Paragraph-level evidence fields
  scope_type: string | null;
  scope_text: string | null;
  trigger_spans: string[] | null;
  evidence_heading_path: string | null;
}

export interface FinalesThema {
  id: string;
  titel: string;
  kategorie: string;
  risikostufe: string;
  kurzbeschreibung: string;
  warum_verhandlungsrelevant: string;
  alternativformulierung: string;
  bieterfrage: string;
  verhandlungsargumente: string[];
  fundstellen: FinalesThemaFundstelle[];
  sortierung: number;
}

export interface VerworfenesThema {
  id: string;
  titel: string;
  kategorie: string;
  grund: string;
}

export interface FinalEditorialResult {
  finale_themen: FinalesThema[];
  verworfene_themen: VerworfenesThema[];
  metriken: {
    anzahl_cluster_themen_vorher: number;
    anzahl_finale_themen_nachher: number;
    anzahl_verworfene_themen: number;
    hat_editorial: boolean;
    anzahl_ausgewaehlte_evidenzen: number;
  };
}

// --- Analysis Case types (multi-document) ---

export interface CaseDocument {
  id: string;
  analysis_case_id: string;
  filename: string;
  original_mime_type: string | null;
  sha256: string | null;
  page_count: number | null;
  char_count: number | null;
  language: string | null;
  document_type: string;
  document_role_rank: number;
  status: string;
  parse_status: string;
  classification_status: string;
  created_at: string;
  error_message: string | null;
}

export interface AnalysisCase {
  id: string;
  external_case_ref: string | null;
  title: string;
  customer_name: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  total_documents: number;
  total_pages: number;
  total_characters: number;
  total_chunks: number;
  total_findings: number;
  total_themes: number;
  total_final_themes: number;
  failure_reason: string | null;
  documents?: CaseDocument[];
  processing_summary?: Record<string, unknown> | null;
}

export interface PositiveControl {
  id: string;
  analysis_case_id: string;
  case_document_id: string;
  document_section_id: string | null;
  control_type: string;
  control_value: string;
  source_text: string;
  status: string;
  notes: string | null;
  created_at: string;
}

export interface DocumentSection {
  id: string;
  case_document_id: string;
  section_index: number;
  page_from: number | null;
  page_to: number | null;
  heading_path: string | null;
  section_type: string;
  char_count: number;
  token_estimate: number;
  routing: string | null;
  routing_reason: string | null;
}

export interface PolicyRule {
  id: string;
  name: string;
  description: string | null;
  rule_type: string;
  match_scope: string;
  pattern_type: string;
  action: string;
  priority: number;
  is_active: boolean;
  conditions_json: Record<string, unknown> | null;
}

export interface PolicyProfile {
  id: string;
  name: string;
  version: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
  rules: PolicyRule[];
}

// --- Case Theme types (multi-document pipeline) ---

export interface ThemeEvidence {
  id: string;
  finding_id: string;
  evidence_role: string;
  rank: number;
  kurzbeschreibung: string | null;
  kategorie: string | null;
  risikostufe: string | null;
  textstelle: string | null;
  // Paragraph-level evidence fields
  scope_type: string | null;
  scope_text: string | null;
  trigger_spans: string[] | null;
  evidence_heading_path: string | null;
}

export interface CaseTheme {
  id: string;
  analysis_case_id: string;
  category: string;
  canonical_title: string;
  canonical_summary: string | null;
  severity: string;
  source_finding_count: number;
  source_document_count: number;
  conflict_detected: boolean;
  conflict_summary: string | null;
  final_selected: boolean;
  final_rank: number | null;
  final_editorial_json: {
    editorial_title?: string;
    editorial_summary?: string;
    alternativformulierung?: string;
    bieterfrage?: string;
    verhandlungsargumente?: string[];
  } | null;
  final_rejection_reason: string | null;
  final_selection_basis: string | null;
  created_at: string;
  evidence: ThemeEvidence[];
}

export interface CaseThemesResponse {
  themes: CaseTheme[];
  total_themes: number;
  total_final: number;
  total_findings: number;
}

export interface Einstellung {
  id: string;
  schluessel: string;
  wert: string;
  beschreibung: string | null;
  aktualisiert_am: string;
}

export interface ProtokollEintrag {
  id: string;
  ebene: string;
  nachricht: string;
  details: Record<string, unknown> | null;
  erstellt_am: string;
}
