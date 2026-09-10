import re
import shutil
import subprocess
from pathlib import Path

import streamlit as st


# =========================
# Configuration
# =========================

DOSSIER_TRAVAIL = Path("workspace")
DOSSIER_VOD = DOSSIER_TRAVAIL / "vod"
DOSSIER_EXTRAITS = DOSSIER_TRAVAIL / "extraits"

DOSSIER_VOD.mkdir(parents=True, exist_ok=True)
DOSSIER_EXTRAITS.mkdir(parents=True, exist_ok=True)


# =========================
# Fonctions utilitaires
# =========================

def verifier_url_twitch(url: str) -> bool:
    """
    Vérifie que l'URL correspond à une VOD Twitch.
    Exemple accepté :
    https://www.twitch.tv/videos/123456789
    """
    motif = r"^https?://(www\.)?twitch\.tv/videos/\d+/?$"
    return bool(re.match(motif, url.strip()))


def nettoyer_dossier(dossier: Path):
    """
    Supprime les anciens fichiers téléchargés.
    """
    if dossier.exists():
        for element in dossier.iterdir():
            if element.is_file() or element.is_symlink():
                element.unlink()
            elif element.is_dir():
                shutil.rmtree(element)

    dossier.mkdir(parents=True, exist_ok=True)


def telecharger_vod(url: str) -> Path:
    """
    Télécharge une VOD Twitch avec yt-dlp.
    """
    nettoyer_dossier(DOSSIER_VOD)

    fichier_sortie = DOSSIER_VOD / "vod.%(ext)s"

    commande = [
        "yt-dlp",
        "--no-playlist",
        "--newline",
        "--retries", "10",
        "--fragment-retries", "10",
        "-f", "bestvideo+bestaudio/best",
        "--merge-output-format", "mp4",
        "-o", str(fichier_sortie),
        url.strip(),
    ]

    resultat = subprocess.run(
        commande,
        capture_output=True,
        text=True
    )

    if resultat.returncode != 0:
        raise RuntimeError(
            resultat.stderr[-3000:]
            if resultat.stderr
            else "Le téléchargement a échoué."
        )

    fichiers_video = list(DOSSIER_VOD.glob("vod.*"))

    fichiers_video = [
        fichier for fichier in fichiers_video
        if fichier.suffix.lower() in [".mp4", ".mkv", ".webm", ".mov"]
    ]

    if not fichiers_video:
        raise FileNotFoundError(
            "La vidéo n'a pas été trouvée après le téléchargement."
        )

    return fichiers_video[0]


def creer_extrait_test(video_path: Path, debut: int, duree: int) -> Path:
    """
    Crée un extrait simple avec FFmpeg.

    Cette fonction sert d'exemple.
    Elle pourra ensuite être remplacée par ton système
    d'analyse automatique des moments importants.
    """
    nettoyer_dossier(DOSSIER_EXTRAITS)

    extrait_path = DOSSIER_EXTRAITS / "extrait_test.mp4"

    commande = [
        "ffmpeg",
        "-y",
        "-ss", str(debut),
        "-i", str(video_path),
        "-t", str(duree),
        "-c:v", "libx264",
        "-c:a", "aac",
        "-movflags", "+faststart",
        str(extrait_path),
    ]

    resultat = subprocess.run(
        commande,
        capture_output=True,
        text=True
    )

    if resultat.returncode != 0:
        raise RuntimeError(
            resultat.stderr[-3000:]
            if resultat.stderr
            else "La création de l'extrait a échoué."
        )

    return extrait_path


# =========================
# Interface Streamlit
# =========================

st.set_page_config(
    page_title="Analyseur de VOD Twitch",
    page_icon="🎬",
    layout="centered"
)

st.title("🎬 Analyseur de VOD Twitch")

st.write(
    "Colle le lien d'une VOD Twitch publique. "
    "La vidéo sera téléchargée directement sur le serveur."
)

url_vod = st.text_input(
    "Lien de la VOD Twitch",
    placeholder="https://www.twitch.tv/videos/123456789"
)

if st.button("⬇️ Télécharger la VOD", use_container_width=True):

    if not url_vod:
        st.warning("Colle d'abord un lien Twitch.")
        st.stop()

    if not verifier_url_twitch(url_vod):
        st.error(
            "Lien invalide. Utilise un lien de ce type : "
            "https://www.twitch.tv/videos/123456789"
        )
        st.stop()

    try:
        with st.spinner(
            "Téléchargement de la VOD en cours... "
            "Cela peut prendre du temps pour une vidéo lourde."
        ):
            video_path = telecharger_vod(url_vod)

        st.session_state["video_path"] = str(video_path)

        st.success("✅ VOD téléchargée avec succès !")

    except FileNotFoundError:
        st.error(
            "yt-dlp ou FFmpeg n'est pas installé sur le serveur."
        )

    except Exception as erreur:
        st.error(f"Erreur pendant le téléchargement : {erreur}")


# =========================
# Affichage de la vidéo
# =========================

if "video_path" in st.session_state:

    video_path = Path(st.session_state["video_path"])

    if video_path.exists():

        st.subheader("📺 VOD téléchargée")

        st.video(str(video_path))

        st.divider()

        st.subheader("✂️ Créer un extrait de test")

        debut = st.number_input(
            "Début de l'extrait, en secondes",
            min_value=0,
            value=0,
            step=1
        )

        duree = st.number_input(
            "Durée de l'extrait, en secondes",
            min_value=1,
            value=30,
            step=1
        )

        if st.button("✂️ Créer l'extrait", use_container_width=True):

            try:
                with st.spinner("Création de l'extrait..."):
                    extrait_path = creer_extrait_test(
                        video_path,
                        int(debut),
                        int(duree)
                    )

                st.success("✅ Extrait créé !")
                st.video(str(extrait_path))

                with open(extrait_path, "rb") as fichier:
                    st.download_button(
                        label="⬇️ Télécharger l'extrait",
                        data=fichier,
                        file_name="extrait_twitch.mp4",
                        mime="video/mp4",
                        use_container_width=True
                    )

            except Exception as erreur:
                st.error(f"Erreur pendant la création : {erreur}")
