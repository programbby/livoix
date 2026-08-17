import asyncio
import edge_tts
import pdfplumber
import re
import os
import sys
import time
import logging
from pathlib import Path
from langdetect import detect, LangDetectException, DetectorFactory

logging.getLogger("pdfminer").setLevel(logging.ERROR)

DetectorFactory.seed = 0

VOIX_PAR_LANGUE = {
    "fr": "fr-FR-DeniseNeural",
    "en": "en-US-JennyNeural",
    "es": "es-ES-ElviraNeural",
    "de": "de-DE-KatjaNeural",
    "it": "it-IT-ElsaNeural",
    "pt": "pt-BR-FranciscaNeural",
    "nl": "nl-NL-FennaNeural",
    "pl": "pl-PL-AgnieszkaNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "ja": "ja-JP-NanamiNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "ar": "ar-SA-ZariyahNeural",
}
VOIX_DEFAUT = "fr-FR-DeniseNeural"


def detecter_voix(texte):
    try:
        langue = detect(texte[:2000])
        voix = VOIX_PAR_LANGUE.get(langue, VOIX_DEFAUT)
        print(f"   Langue détectée : {langue} → {voix}")
        return voix
    except LangDetectException:
        print(f"   Langue non détectée → voix par défaut")
        return VOIX_DEFAUT


def extraire_texte_pdf(chemin_pdf):
    texte = ""
    try:
        with pdfplumber.open(chemin_pdf) as pdf:
            for page in pdf.pages:
                contenu = page.extract_text()
                if contenu:
                    texte += contenu + "\n"
    except Exception as e:
        print(f"❌ Impossible d'ouvrir le PDF : {e}")
        print("   Si le PDF est protégé par mot de passe, retire la protection d'abord.")
        sys.exit(1)
    return texte


def nettoyer_texte(texte):
    texte = re.sub(r'https?://\S+', '', texte)
    texte = re.sub(r'www\.\S+', '', texte)

    # Lignes de sommaire (points de remplissage vrais : ....)
    texte = re.sub(r'^.{1,80}\.{4,}\s*\d+\s*$', '', texte, flags=re.MULTILINE)

    # Numéros de page
    texte = re.sub(r'^\s*[-–]?\s*\d+\s*[-–]?\s*$', '', texte, flags=re.MULTILINE)
    texte = re.sub(r'^\s*[Pp]age\s+\d+.*$', '', texte, flags=re.MULTILINE)

    # Réparer les mots coupés en fin de ligne (ex: "impor-\ntant" → "important")
    texte = re.sub(r'-\n([a-zA-ZÀ-ÿ])', r'\1', texte)

    # Sauts de ligne simples → espace (fins de ligne de mise en page)
    texte = re.sub(r'(?<!\n)\n(?!\n)', ' ', texte)

    # Normaliser les espaces et sauts de ligne
    texte = re.sub(r' {2,}', ' ', texte)
    texte = re.sub(r'\n{3,}', '\n\n', texte)

    return texte.strip()


async def pdf_vers_audio(chemin_pdf, dossier_sortie):
    nom_fichier = Path(chemin_pdf).stem

    print(f"\n📖 Lecture du PDF...")
    texte = extraire_texte_pdf(chemin_pdf)
    texte = nettoyer_texte(texte)

    if not texte or len(texte) < 20:
        print("❌ Aucun texte extractible du PDF (probablement un scan/image).")
        print("   Solution : utiliser un OCR (Adobe Acrobat, Tesseract) avant.")
        sys.exit(1)

    mots = len(texte.split())
    minutes_estimees = mots / 150
    print(f"   {len(texte)} caractères — environ {mots} mots → ~{minutes_estimees:.0f} min d'audio")

    voix = detecter_voix(texte)

    fichier_final = os.path.join(dossier_sortie, f"{nom_fichier}.mp3")
    if os.path.exists(fichier_final):
        reponse = input(f"⚠️  {nom_fichier}.mp3 existe déjà. Écraser ? (o/n) : ")
        if reponse.lower() != "o":
            print("Annulé.")
            sys.exit(0)

    print(f"   Génération en cours...\n")

    try:
        debut = time.time()
        communicate = edge_tts.Communicate(texte, voix)
        await communicate.save(fichier_final)
        duree = time.time() - debut
    except edge_tts.exceptions.NoAudioReceived:
        print("❌ Microsoft n'a rien renvoyé.")
        print(f"   Le texte fait {len(texte)} caractères — peut-être trop long en une seule requête.")
        print("   Réessaie plus tard ou découpe le PDF en plusieurs fichiers.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Erreur pendant la génération audio : {e}")
        sys.exit(1)

    taille_mb = os.path.getsize(fichier_final) / (1024 * 1024)
    print(f"✅ Terminé en {duree/60:.1f} min ! {fichier_final}")
    print(f"   Taille : {taille_mb:.1f} MB")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python livoix.py <chemin_vers_ton_pdf>")
        print("Exemple: python livoix.py C:\\Users\\Miguel\\Documents\\mon_livre.pdf")
        sys.exit(1)

    chemin_pdf = sys.argv[1]

    if not os.path.exists(chemin_pdf):
        print(f"Erreur : fichier introuvable → {chemin_pdf}")
        sys.exit(1)

    dossier_audio = r"C:\Users\Administrator\OneDrive\Desktop\livres audios"
    os.makedirs(dossier_audio, exist_ok=True)

    asyncio.run(pdf_vers_audio(chemin_pdf, dossier_audio))
