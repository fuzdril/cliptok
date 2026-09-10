import re
import shutil
import subprocess
from pathlib import Path

import streamlit as st
from faster_whisper import WhisperModel


# =====================================================
# CONFIGURATION
# =====================================================

BASE_DIR = Path("workspace")
VOD_DIR = BASE_DIR / "vod"
AUDIO_DIR = BASE_DIR / "audio"
CLIPS_DIR = BASE_DIR / "clips"

for dossier in [VOD_DIR, AUDIO_DIR, CLIPS_DIR]:
    dossier.mkdir(parents=True, exist_ok=True)


# =====================================================
# OUTILS
# =====================================================

def vider_dossier(dossier: Path):
    for fichier in dossier.iterdir():
        if fichier.is_file():
            fichier.unlink()
        elif fichier.is_dir():
            shutil.rmtree(fichier)


def verifier_url_twitch(url: str) -> bool:
    motif = r"^https?://(www\.)?twitch\.tv/videos/\d+/?$"
    return bool(re.match(motif, url.strip()))


def lancer_commande(commande):
    resultat = subprocess.run(
        commande,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if resultat.returncode != 0:
        raise RuntimeError(resultat.stderr[-4000:])

    return resultat


# =====================================================
# TÉLÉCHARGEMENT DE LA VOD
# =====================================================

def telecharger_vod(url: str) -> Path:
    vider_dossier(VOD_DIR)

    sortie = VOD_DIR / "vod.%(ext)s"

    commande = [
        "yt-dlp",
        "--no-playlist",
        "--newline",
        "--retries", "10",
        "--fragment-retries", "10",
        "-f", "bestvideo+bestaudio/best",
        "--merge-output-format", "mp4",
        "-o", str(sortie),
        url.strip()
    ]

    lancer_commande(commande)

    fichiers = [
        fichier for fichier in VOD_DIR.iterdir()
        if fichier.suffix.lower() in [
            ".mp4", ".mkv", ".webm", ".mov"
        ]
    ]

    if not fichiers:
        raise FileNotFoundError(
            "La VOD n'a pas été téléchargée."
        )

    return fichiers[0]


# =====================================================
# EXTRACTION AUDIO
# =====================================================

def extraire_audio(video_path: Path) -> Path:
    audio_path = AUDIO_DIR / "audio.wav"

    commande = [
        "ffmpeg",
        "-y",
        "-i", str(video_path),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(audio_path)
    ]

    lancer_commande(commande)

    if not audio_path.exists():
        raise FileNotFoundError(
            "Impossible d'extraire l'audio."
        )

    return audio_path


# =====================================================
# TRANSCRIPTION
# =====================================================

@st.cache_resource
def charger_modele():
    token = st.secrets.get("HF_TOKEN", None)

    return WhisperModel(
        "small",
        device="cpu",
        compute_type="int8",
        token=token
    )
def transcrire_audio(audio_path: Path):
    modele = charger_modele()

    segments, informations = modele.transcribe(
        str(audio_path),
        language="fr",
        vad_filter=True,
        beam_size=5
    )

    transcription = []

    for segment in segments:
        texte = segment.text.strip()

        if texte:
            transcription.append({
                "debut": float(segment.start),
                "fin": float(segment.end),
                "texte": texte
            })

    return transcription


# =====================================================
# DÉTECTION DES MOMENTS INTÉRESSANTS
# =====================================================

MOTS_IMPORTANTS = {
    "incroyable": 5,
    "impossible": 5,
    "clutch": 6,
    "gagné": 4,
    "gagner": 4,
    "victoire": 4,
    "attention": 3,
    "regardez": 3,
    "oh": 2,
    "wow": 4,
    "wtf": 5,
    "mdr": 3,
    "mort": 3,
    "tuer": 3,
    "tuez": 3,
    "rage": 4,
    "putain": 2,
    "merde": 2,
    "non": 1,
    "oui": 1,
    "premier": 2,
    "record": 5,
    "nouveau": 2,
    "hack": 4,
    "bug": 3,
    "secret": 3,
    "important": 2,
}


def calculer_score(texte: str) -> int:
    texte_minuscule = texte.lower()
    score = 0

    for mot, valeur in MOTS_IMPORTANTS.items():
        score += texte_minuscule.count(mot) * valeur

    score += texte.count("!") * 2
    score += texte.count("?")

    if len(texte.split()) >= 12:
        score += 1

    return score


def detecter_meilleurs_moments(
    transcription,
    duree_clip=45,
    nombre_clips=5
):
    candidats = []

    for segment in transcription:
        score = calculer_score(segment["texte"])

        if score <= 0:
            continue

        debut = max(0, segment["debut"] - 12)
        fin = segment["fin"] + 20

        if fin - debut < duree_clip:
            fin = debut + duree_clip

        texte_autour = []

        for autre in transcription:
            if autre["fin"] >= debut and autre["debut"] <= fin:
                texte_autour.append(autre["texte"])

        candidats.append({
            "debut": debut,
            "fin": fin,
            "score": score,
            "titre": " ".join(texte_autour)[:100]
        })

    candidats.sort(
        key=lambda element: element["score"],
        reverse=True
    )

    moments = []

    for candidat in candidats:
        chevauchement = False

        for moment in moments:
            debut_max = max(
                candidat["debut"],
                moment["debut"]
            )
            fin_min = min(
                candidat["fin"],
                moment["fin"]
            )

            if fin_min > debut_max:
                chevauchement = True
                break

        if not chevauchement:
            moments.append(candidat)

        if len(moments) >= nombre_clips:
            break

    return moments


# =====================================================
# SOUS-TITRES SRT
# =====================================================

def convertir_temps_srt(secondes: float) -> str:
    heures = int(secondes // 3600)
    minutes = int((secondes % 3600) // 60)
    secondes_entieres = int(secondes % 60)
    millisecondes = int(
        (secondes - int(secondes)) * 1000
    )

    return (
        f"{heures:02d}:{minutes:02d}:"
        f"{secondes_entieres:02d},{millisecondes:03d}"
    )


def creer_srt(transcription, debut, fin, chemin_srt):
    lignes = []
    numero = 1

    for segment in transcription:
        if segment["fin"] < debut or segment["debut"] > fin:
            continue

        debut_local = max(
            0,
            segment["debut"] - debut
        )

        fin_local = min(
            fin - debut,
            segment["fin"] - debut
        )

        lignes.append(str(numero))
        lignes.append(
            f"{convertir_temps_srt(debut_local)} --> "
            f"{convertir_temps_srt(fin_local)}"
        )
        lignes.append(segment["texte"])
        lignes.append("")

        numero += 1

    chemin_srt.write_text(
        "\n".join(lignes),
        encoding="utf-8"
    )


# =====================================================
# CRÉATION D'UN CLIP TIKTOK
# =====================================================

def creer_clip_vertical(
    video_path: Path,
    transcription,
    moment,
    numero: int
) -> Path:

    debut = moment["debut"]
    fin = moment["fin"]
    duree = fin - debut

    chemin_clip = CLIPS_DIR / f"clip_{numero}.mp4"
    chemin_srt = CLIPS_DIR / f"clip_{numero}.srt"

    creer_srt(
        transcription,
        debut,
        fin,
        chemin_srt
    )

    filtre = (
        "scale=1080:1920:"
        "force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        "subtitles=" + str(chemin_srt).replace("\\", "/")
    )

    commande = [
        "ffmpeg",
        "-y",
        "-ss", str(debut),
        "-i", str(video_path),
        "-t", str(duree),
        "-vf", filtre,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(chemin_clip)
    ]

    lancer_commande(commande)

    if not chemin_clip.exists():
        raise FileNotFoundError(
            f"Le clip {numero} n'a pas été créé."
        )

    return chemin_clip


# =====================================================
# INTERFACE STREAMLIT
# =====================================================

st.set_page_config(
    page_title="Twitch vers TikTok",
    page_icon="🎬",
    layout="centered"
)

st.title("🎬 Twitch VOD → extraits TikTok")

st.write(
    "Colle une URL de VOD Twitch. "
    "L'application détectera automatiquement les passages "
    "les plus intéressants et créera des clips verticaux."
)

url_vod = st.text_input(
    "URL de la VOD Twitch",
    placeholder="https://www.twitch.tv/videos/123456789"
)

nombre_clips = st.slider(
    "Nombre d'extraits à créer",
    min_value=1,
    max_value=10,
    value=5
)

duree_clip = st.slider(
    "Durée approximative des extraits",
    min_value=15,
    max_value=90,
    value=45
)

if st.button(
    "🚀 Analyser la VOD",
    use_container_width=True
):

    if not url_vod:
        st.warning("Colle d'abord une URL Twitch.")
        st.stop()

    if not verifier_url_twitch(url_vod):
        st.error(
            "URL invalide. Exemple : "
            "https://www.twitch.tv/videos/123456789"
        )
        st.stop()

    try:
        vider_dossier(AUDIO_DIR)
        vider_dossier(CLIPS_DIR)

        # Barre et texte de progression
        barre_progression = st.progress(
            0,
            text="Progression : 0%"
        )

        texte_progression = st.empty()

        with st.status(
            "Traitement de la VOD en cours...",
            expanded=True
        ) as statut:

            # Étape 1
            pourcentage = 5
            texte_progression.write(
                f"⏳ Progression : {pourcentage}% — "
                "Préparation..."
            )
            barre_progression.progress(
                pourcentage,
                text=f"Progression : {pourcentage}%"
            )

            # Étape 2
            st.write("⬇️ Téléchargement de la VOD...")
            video_path = telecharger_vod(url_vod)

            pourcentage = 20
            texte_progression.write(
                f"⏳ Progression : {pourcentage}% — "
                "VOD téléchargée"
            )
            barre_progression.progress(
                pourcentage,
                text=f"Progression : {pourcentage}%"
            )

            # Étape 3
            st.write("🎧 Extraction de l'audio...")
            audio_path = extraire_audio(video_path)

            pourcentage = 35
            texte_progression.write(
                f"⏳ Progression : {pourcentage}% — "
                "Audio extrait"
            )
            barre_progression.progress(
                pourcentage,
                text=f"Progression : {pourcentage}%"
            )

            # Étape 4
            st.write("📝 Transcription avec Whisper...")
            transcription = transcrire_audio(audio_path)

            pourcentage = 60
            texte_progression.write(
                f"⏳ Progression : {pourcentage}% — "
                "Transcription terminée"
            )
            barre_progression.progress(
                pourcentage,
                text=f"Progression : {pourcentage}%"
            )

            if not transcription:
                raise RuntimeError(
                    "Aucune parole n'a été détectée dans la VOD."
                )

            # Étape 5
            st.write("🔎 Recherche des meilleurs moments...")
            moments = detecter_meilleurs_moments(
                transcription,
                duree_clip=duree_clip,
                nombre_clips=nombre_clips
            )

            pourcentage = 65
            texte_progression.write(
                f"⏳ Progression : {pourcentage}% — "
                "Moments détectés"
            )
            barre_progression.progress(
                pourcentage,
                text=f"Progression : {pourcentage}%"
            )

            if not moments:
                raise RuntimeError(
                    "Aucun moment intéressant n'a été détecté."
                )

            # Étape 6
            st.write("✂️ Création des clips verticaux...")

            clips = []
            total_clips = len(moments)

            for numero, moment in enumerate(moments, start=1):
                clip = creer_clip_vertical(
                    video_path,
                    transcription,
                    moment,
                    numero
                )

                clips.append({
                    "fichier": clip,
                    "moment": moment
                })

                pourcentage = 65 + int(
                    (numero / total_clips) * 30
                )

                texte_progression.write(
                    f"⏳ Progression : {pourcentage}% — "
                    f"Clip {numero}/{total_clips} créé"
                )

                barre_progression.progress(
                    pourcentage,
                    text=f"Progression : {pourcentage}%"
                )

            # Fin
            barre_progression.progress(
                100,
                text="Progression : 100% — Terminé !"
            )

            texte_progression.success(
                "✅ Traitement terminé à 100%."
            )

            statut.update(
                label="✅ Analyse terminée !",
                state="complete"
            )

        st.success(
            f"{len(clips)} extrait(s) créé(s)."
        )

        for element in clips:
            clip = element["fichier"]
            moment = element["moment"]

            st.divider()

            st.subheader(
                f"Clip — score {moment['score']}"
            )

            st.write(
                f"De {int(moment['debut'])} à "
                f"{int(moment['fin'])} secondes"
            )

            st.caption(moment["titre"])

            st.video(str(clip))

            with open(clip, "rb") as fichier:
                st.download_button(
                    label=f"⬇️ Télécharger {clip.name}",
                    data=fichier,
                    file_name=clip.name,
                    mime="video/mp4",
                    key=clip.name,
                    use_container_width=True
                )

    except Exception as erreur:
        st.error(f"❌ Erreur : {erreur}")
