import os
import re
import json
import subprocess
from pathlib import Path

import streamlit as st
from openai import OpenAI

OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]

client = OpenAI(api_key=OPENAI_API_KEY)

BASE_DIR = Path("workspace")
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ==================================================
# Style mobile
# ==================================================

st.set_page_config(
    page_title="ClipTok",
    page_icon="🎬",
    layout="centered",
    initial_sidebar_state="collapsed"
)

st.markdown(
    """
    <style>
        #MainMenu {
            visibility: hidden;
        }

        footer {
            visibility: hidden;
        }

        header {
            visibility: hidden;
        }

        .block-container {
            padding: 1rem 0.8rem 3rem 0.8rem;
            max-width: 720px;
        }

        h1 {
            font-size: 1.8rem !important;
            text-align: center;
            margin-bottom: 0.3rem;
        }

        h2, h3 {
            font-size: 1.25rem !important;
        }

        p, label, div {
            font-size: 1rem;
        }

        button {
            min-height: 3.2rem !important;
            border-radius: 14px !important;
            font-weight: 700 !important;
        }

        [data-testid="stFileUploader"] {
            border: 2px dashed #ff2d55;
            border-radius: 16px;
            padding: 0.8rem;
        }

        [data-testid="stDownloadButton"] button {
            background-color: #111111 !important;
            color: white !important;
            width: 100%;
        }

        video {
            width: 100%;
            max-height: 550px;
            border-radius: 16px;
        }

        .app-subtitle {
            text-align: center;
            color: #666;
            margin-bottom: 1.2rem;
        }

        .clip-card {
            padding: 1rem;
            border-radius: 18px;
            background: #f7f7f7;
            margin: 1rem 0;
        }

        .badge {
            background: #ff2d55;
            color: white;
            padding: 0.25rem 0.6rem;
            border-radius: 999px;
            font-weight: bold;
            font-size: 0.8rem;
        }

        @media (prefers-color-scheme: dark) {
            .clip-card {
                background: #202020;
            }
        }
    </style>
    """,
    unsafe_allow_html=True
)


# ==================================================
# Fonctions
# ==================================================

def nettoyer_nom(texte):
    texte = texte.lower()
    texte = re.sub(r"[^a-zA-Z0-9À-ÿ_-]+", "_", texte)
    return texte[:70]


def extraire_audio(video_path, audio_path):
    commande = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "mp3",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(audio_path)
    ]

    subprocess.run(
        commande,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )


def transcrire(audio_path):
    with open(audio_path, "rb") as audio:
        resultat = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio,
            response_format="verbose_json",
            timestamp_granularities=["segment"]
        )

    return resultat


def analyser_segments(segments, nombre, duree_min, duree_max):
    donnees = []

    for segment in segments:
        donnees.append({
            "debut": round(segment.start, 2),
            "fin": round(segment.end, 2),
            "texte": segment.text
        })

    prompt = f"""
Tu es un expert des vidéos TikTok.

Sélectionne les {nombre} meilleurs extraits dans cette transcription.

Critères :
- passage intéressant dès les premières secondes ;
- conseil utile ;
- phrase surprenante ;
- histoire personnelle ;
- moment drôle ;
- opinion forte ;
- révélation ;
- extrait compréhensible seul.

Contraintes :
- durée entre {duree_min} et {duree_max} secondes ;
- pas de chevauchement ;
- évite les introductions inutiles ;
- commence autant que possible au début d'une phrase.

Réponds uniquement avec un JSON valide :

[
  {{
    "debut": 10.5,
    "fin": 42.8,
    "titre": "Titre court",
    "raison": "Pourquoi cet extrait est intéressant",
    "score": 9
  }}
]

Transcription :
{json.dumps(donnees, ensure_ascii=False)}
"""

    resultat = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt
    )

    texte = resultat.output_text.strip()
    texte = texte.replace("```json", "")
    texte = texte.replace("```", "")
    texte = texte.strip()

    return json.loads(texte)


def creer_clip(video_path, sortie, debut, fin):
    duree = max(1, fin - debut)

    filtre = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920"
    )

    commande = [
        "ffmpeg",
        "-y",
        "-ss",
        str(debut),
        "-i",
        str(video_path),
        "-t",
        str(duree),
        "-vf",
        filtre,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "21",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(sortie)
    ]

    subprocess.run(
        commande,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )


def temps(secondes):
    minutes = int(secondes // 60)
    secondes = int(secondes % 60)
    return f"{minutes:02d}:{secondes:02d}"


# ==================================================
# Interface
# ==================================================

st.title("🎬 ClipTok")

st.markdown(
    '<div class="app-subtitle">'
    "Transforme automatiquement tes longues vidéos en extraits TikTok"
    "</div>",
    unsafe_allow_html=True
)

with st.expander("⚙️ Paramètres", expanded=False):
    nombre_extraits = st.slider(
        "Nombre d'extraits",
        min_value=1,
        max_value=8,
        value=3
    )

    duree_min = st.slider(
        "Durée minimale",
        min_value=10,
        max_value=60,
        value=20
    )

    duree_max = st.slider(
        "Durée maximale",
        min_value=20,
        max_value=90,
        value=50
    )

st.subheader("1. Choisis une vidéo")

video = st.file_uploader(
    "📱 Appuie ici pour choisir une vidéo",
    type=["mp4", "mov", "m4v", "webm", "avi"],
    help="Tu peux sélectionner une vidéo depuis ta galerie ou ta caméra."
)

if not video:
    st.info(
        "Conseil : utilise une vidéo horizontale ou verticale avec de la parole "
        "pour obtenir les meilleurs résultats."
    )
    st.stop()

extension = Path(video.name).suffix.lower()
video_path = UPLOAD_DIR / f"video_source{extension}"
audio_path = BASE_DIR / "audio.mp3"

with open(video_path, "wb") as fichier:
    fichier.write(video.getbuffer())

st.subheader("2. Aperçu")

st.video(str(video_path))

st.subheader("3. Création automatique")

if st.button(
    "🚀 Créer mes extraits",
    type="primary",
    use_container_width=True
):
    if duree_min >= duree_max:
        st.error(
            "La durée minimale doit être inférieure à la durée maximale."
        )
        st.stop()

    try:
        progress = st.progress(0)
        message = st.empty()

        message.write("🎵 Préparation de l'audio...")
        extraire_audio(video_path, audio_path)
        progress.progress(25)

        message.write("📝 Transcription de la vidéo...")
        transcription = transcrire(audio_path)

        if not transcription.segments:
            st.error("Aucune parole n'a été détectée dans la vidéo.")
            st.stop()

        progress.progress(50)

        message.write("🧠 Recherche des meilleurs passages...")
        clips = analyser_segments(
            transcription.segments,
            nombre_extraits,
            duree_min,
            duree_max
        )

        progress.progress(70)

        st.subheader("✅ Tes extraits")

        for index, clip in enumerate(clips, start=1):
            debut = float(clip["debut"])
            fin = float(clip["fin"])
            titre = clip.get("titre", f"Extrait {index}")
            raison = clip.get("raison", "")
            score = clip.get("score", "?")

            nom = f"clip_{index}_{nettoyer_nom(titre)}.mp4"
            sortie = OUTPUT_DIR / nom

            message.write(f"🎬 Création de l'extrait {index}...")
            creer_clip(video_path, sortie, debut, fin)

            st.markdown(
                f"""
                <div class="clip-card">
                    <span class="badge">EXTRAIT {index}</span>
                    <h3>{titre}</h3>
                    <p>
                        ⏱️ {temps(fin - debut)}
                        &nbsp; • &nbsp;
                        ⭐ Score : {score}/10
                    </p>
                    <p>{raison}</p>
                </div>
                """,
                unsafe_allow_html=True
            )

            st.video(str(sortie))

            with open(sortie, "rb") as fichier:
                st.download_button(
                    "⬇️ Télécharger cet extrait",
                    data=fichier,
                    file_name=nom,
                    mime="video/mp4",
                    use_container_width=True,
                    key=f"download_{index}"
                )

        progress.progress(100)
        message.success("Tous les extraits sont prêts ! 🎉")

    except json.JSONDecodeError:
        st.error(
            "L'analyse a échoué. Relance le traitement ou réduis la durée "
            "de la vidéo."
        )

    except subprocess.CalledProcessError:
        st.error(
            "FFmpeg n'est pas disponible sur le serveur."
        )

    except Exception as erreur:
        st.error("Une erreur est survenue.")
        st.exception(erreur)
