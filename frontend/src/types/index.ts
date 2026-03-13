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
