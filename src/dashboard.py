import streamlit as st
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from monitoring import charger_interactions

st.set_page_config(page_title="Monitoring — Puls-Events", layout="wide")
st.title("Monitoring RAG — Puls-Events")

interactions = charger_interactions()
if not interactions:
    st.info("Aucune interaction enregistrée pour l'instant.")
    st.stop()

df = pd.DataFrame(interactions)
df["timestamp"] = pd.to_datetime(df["timestamp"])

# ── Métriques clés ──
taux_echec = df["est_echec"].mean()
latence_p50 = df["duree_ms"].quantile(0.50) / 1000
latence_p95 = df["duree_ms"].quantile(0.95) / 1000

df_fb = df[df["feedback"].notna()]
taux_positif = df_fb["feedback"].mean() if len(df_fb) > 0 else None

c1, c2, c3, c4 = st.columns(4)
c1.metric("Interactions", len(df))
c2.metric("Taux d'échec", f"{taux_echec*100:.1f}%")
c3.metric("Latence p50 / p95", f"{latence_p50:.1f}s / {latence_p95:.1f}s")
c4.metric("Feedback positif",
          f"{taux_positif*100:.0f}%" if taux_positif is not None else "–")

# ── Alertes ──
alertes = []
if taux_echec > 0.10:
    alertes.append(f"Taux d'échec élevé : {taux_echec*100:.1f}% (seuil 10%)")
if latence_p95 > 5:
    alertes.append(f"Latence p95 élevée : {latence_p95:.1f}s (seuil 5s)")
if taux_positif is not None and taux_positif < 0.75:
    alertes.append(f"Feedback dégradé : {taux_positif*100:.0f}% (seuil 75%)")

if alertes:
    for a in alertes:
        st.error(a)
else:
    st.success("Tous les indicateurs sont dans les seuils.")

# ── Tendance par jour ──
df["jour"] = df["timestamp"].dt.date
tendance = df.groupby("jour").agg(
    interactions=("id", "count"),
    taux_echec=("est_echec", "mean"),
    latence_moy=("duree_ms", "mean")
).reset_index()

col_g, col_d = st.columns(2)
with col_g:
    st.caption("Interactions par jour")
    st.bar_chart(tendance.set_index("jour")["interactions"])
with col_d:
    st.caption("Taux d'échec par jour")
    st.line_chart(tendance.set_index("jour")["taux_echec"])

# ── Questions en échec (à analyser) ──
st.subheader("Dernières questions sans réponse")
echecs = df[df["est_echec"] == 1][["timestamp", "question", "ville_filtre"]].head(10)
st.dataframe(echecs, use_container_width=True)

# ── Dernières interactions ──
st.subheader("Dernières interactions")
st.dataframe(
    df[["timestamp", "question", "nb_chunks", "duree_ms", "est_echec", "feedback"]].head(20),
    use_container_width=True
)