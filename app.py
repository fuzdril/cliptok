import json
import re
import subprocess
from pathlib import Path

import streamlit as st
from openai import OpenAI


# =========================
# Configuration
# =========================

st.set_page_config(
    page_title="ClipTok",
    page_icon="🎬",
    layout="centered"
)

try:
    API_KEY = st.secrets["OPENAI_API_KEY"]
except Exception:
    API_KEY = ""

if not API_KEY:
    st.error("La clé OPENAI_API_KEY est absente.")
    st.stop()

client = OpenAI(api_key=API_KEY)

BASE_DIR = Path("workspace")
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# =========================
# Fonctions vidéo
# =========================

def extraire_audio(video_path, audio_path):
    commande = [
        "ffmpeg",
        "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "mp3",
        "-ar", "16000",
        "-ac", "1",
        str(audio_path)
    ]

    subprocess.run(
        commande,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )


def obtenir_duree(video_path):
    commande = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]

    resultat = subprocess.run(
        commande,
        capture_output=True,
        text=True,
        check=True
    )

    return float(resultat.stdout.strip())


def transcrire_audio(audio_path):
    with open(audio_path, "rb") as fichier_audio:
        transcription = client.audio.transcriptions.create(
            model="whisper-1",
            file=fichier_audio,
            response_format="verbose_json",
            timestamp_granularities=["segment"]
        )

    return transcription


def analyser_transcription(transcription, nombre_extraits, duree_max):
    segments = []

    for segment in transcription.segments:
        segments.append({
            "start": float(segment.start),
            "end": float(segment.end),
            "text": segment.text.strip()
        })

    prompt = f"""
Tu es un expert des vidéos TikTok.

À partir de cette transcription, sélectionne les {nombre_extraits}
meilleurs passages pour créer des extraits TikTok.

Un bon extrait doit avoir au moins un de ces critères :
- phrase surprenante ;
- conseil utile ;
- moment drôle ;
- opinion forte ;
- émotion ;
- histoire intéressante ;
- phrase qui donne envie de regarder jusqu'à la fin.

Chaque extrait doit durer entre 15 et {duree_max} secondes.

Réponds uniquement avec un JSON valide sous cette forme :

[
  {{
    "start": 12.5,
    "end": 48.0,
    "title": "Titre court de l'extrait",
    "reason": "Pourquoi cet extrait est intéressant"
  }}
]

TRANSCRIPTION :
{json.dumps(segments, ensure_ascii=False)}
"""

    reponse = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.3,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "Tu sélectionnes les meilleurs moments de vidéos pour TikTok."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    contenu = reponse.choices[0].message.content
    donnees = json.loads(contenu)

    if isinstance(donnees, dict):
        for cle in ["clips", "extraits", "results", "resultats"]:
            if cle in donnees:
                donnees = donnees[cle]
                break

    return donnees


def nettoyer_nom(nom):
    nom = re.sub(r"[^a-zA-Z0-9À-ÿ _-]", "", nom)
    nom = nom.strip().replace(" ", "_")
    return nom[:80] or "extrait"


def creer_extrait(video_path, output_path, debut, fin):
    duree = max(1, fin - debut)

    commande = [
        "ffmpeg",
        "-y",
        "-ss", str(debut),
        "-i", str(video_path),
        "-t", str(duree),

        # Format vertical 9:16 pour TikTok
        "-vf",
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920",

        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path)
    ]

    subprocess.run(
        commande,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )


# =========================
# Interface
# =========================

st.title("🎬 ClipTok")
st.write("Transforme automatiquement une vidéo en extraits TikTok.")

video_importee = st.file_uploader(
    "Choisis une vidéo",
    type=["mp4", "mov", "mkv", "webm", "m4v"]
)

with st.expander("⚙️ Paramètres"):
    nombre_extraits = st.slider(
        "Nombre d'extraits",
        min_value=1,
        max_value=10,
        value=3
    )

    duree_max = st.slider(
        "Durée maximale d'un extrait",
        min_value=20,
        max_value=60,
        value=45
    )

if video_importee:
    st.video(video_importee)

    if st.button("🚀 Créer mes extraits", use_container_width=True):
        try:
            nom_video = nettoyer_nom(Path(video_importee.name).stem)

            video_path = UPLOAD_DIR / f"{nom_video}.mp4"
            audio_path = UPLOAD_DIR / f"{nom_video}.mp3"

            with open(video_path, "wb") as fichier:
                fichier.write(video_importee.getbuffer())

            barre = st.progress(0)
            statut = st.empty()

            statut.info("Extraction de l'audio...")
            extraire_audio(video_path, audio_path)
            barre.progress(25)

            statut.info("Transcription de la vidéo...")
            transcription = transcrire_audio(audio_path)
            barre.progress(50)

            statut.info("Recherche des meilleurs passages...")
            extraits = analyser_transcription(
                transcription,
                nombre_extraits,
                duree_max
            )
            barre.progress(65)

            if not extraits:
                st.error("Aucun extrait intéressant n'a été trouvé.")
                st.stop()

            st.subheader("✅ Extraits créés")

            for index, extrait in enumerate(extraits, start=1):
                debut = max(0, float(extrait["start"]))
                fin = float(extrait["end"])

                if fin <= debut:
                    continue

                titre = extrait.get("title", f"Extrait {index}")
                raison = extrait.get("reason", "")

                nom_sortie = (
                    f"{index:02d}_{nettoyer_nom(titre)}.mp4"
                )

                output_path = OUTPUT_DIR / nom_sortie

                statut.info(
                    f"Création de l'extrait {index}/{len(extraits)}..."
                )

                creer_extrait(
                    video_path,
                    output_path,
                    debut,
                    fin
                )

                st.markdown(f"### {index}. {titre}")
                st.caption(
                    f"{int(debut)}s → {int(fin)}s"
                )

                if raison:
                    st.write(raison)

                st.video(str(output_path))

                with open(output_path, "rb") as fichier:
                    st.download_button(
                        label=f"⬇️ Télécharger l'extrait {index}",
                        data=fichier.read(),
                        file_name=nom_sortie,
                        mime="video/mp4",
                        use_container_width=True,
                        key=f"download_{index}"
                    )

            barre.progress(100)
            statut.success("Tous les extraits sont prêts !")

        except subprocess.CalledProcessError:
            st.error(
                "Erreur FFmpeg. Vérifie que FFmpeg est bien installé sur le serveur."
            )

        except Exception as erreur:
            st.error("Une erreur est survenue.")
            st.exception(erreur)
