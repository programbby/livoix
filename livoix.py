import asyncio
import edge_tts
import pdfplumber
import re
import os
import sys
from pathlib import Path

# Voix françaises disponibles (commente/décommente pour changer)
VOIX = "fr-FR-DeniseNeural"   # Femme, France (Denise Natural)
# VOIX = "fr-FR-HenriNeural"  # Homme, France
# VOIX = "fr-CA-AntoineNeural"  # Homme, Québec
# VOIX = "fr-CA-SylvieNeural"   # Femme, Québec

def extraire_texte_pdf(chemin_pdf):
    texte = ""
    with pdfplumber.open(chemin_pdf) as pdf:
        for page in pdf.pages:
            contenu = page.extract_text()
            if contenu:
                texte += contenu + "\n"
    return texte


def nettoyer_texte(texte):
    # Supprimer les URLs
    texte = re.sub(r'https?://\S+', '', texte)
    texte = re.sub(r'www\.\S+', '', texte)

    # Supprimer les lignes de sommaire (texte suivi de points et d'un numéro)
    texte = re.sub(r'^.{1,60}[.\s]{3,}\d+\s*$', '', texte, flags=re.MULTILINE)

    # Supprimer les numéros de page
    texte = re.sub(r'^\s*[-–]?\s*\d+\s*[-–]?\s*$', '', texte, flags=re.MULTILINE)
    texte = re.sub(r'^\s*[Pp]age\s+\d+.*$', '', texte, flags=re.MULTILINE)

    # Réparer les mots coupés en fin de ligne (ex: "impor-\ntant" → "important")
    texte = re.sub(r'-\n([a-zA-ZÀ-ÿ])', r'\1', texte)

    # Remplacer les sauts de ligne simples par un espace (fins de ligne de mise en page)
    # Les doubles sauts de ligne (vrais paragraphes) sont préservés
    texte = re.sub(r'(?<!\n)\n(?!\n)', ' ', texte)

    # Normaliser les espaces multiples
    texte = re.sub(r' {2,}', ' ', texte)

    # Normaliser les sauts de ligne excessifs
    texte = re.sub(r'\n{3,}', '\n\n', texte)

    return texte.strip()


async def pdf_vers_audio(chemin_pdf, dossier_sortie, voix=VOIX):
    nom_fichier = Path(chemin_pdf).stem

    print(f"\n📖 Lecture du PDF...")
    texte = extraire_texte_pdf(chemin_pdf)
    texte = nettoyer_texte(texte)
    print(f"   {len(texte)} caractères extraits")
    print(f"   Voix : {voix}")
    print(f"   Génération en cours (peut prendre quelques minutes)...\n")

    fichier_final = os.path.join(dossier_sortie, f"{nom_fichier}.mp3")

    communicate = edge_tts.Communicate(texte, voix)
    await communicate.save(fichier_final)

    taille_mb = os.path.getsize(fichier_final) / (1024 * 1024)
    print(f"✅ Terminé ! {fichier_final}")
    print(f"   Taille : {taille_mb:.1f} MB")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python livre_audio.py <chemin_vers_ton_pdf>")
        print("Exemple: python livre_audio.py C:\\Users\\Miguel\\Documents\\mon_livre.pdf")
        sys.exit(1)

    chemin_pdf = sys.argv[1]

    if not os.path.exists(chemin_pdf):
        print(f"Erreur : fichier introuvable → {chemin_pdf}")
        sys.exit(1)

    dossier_audio = r"C:\Users\Administrator\OneDrive\Desktop\livres audios"
    os.makedirs(dossier_audio, exist_ok=True)

    asyncio.run(pdf_vers_audio(chemin_pdf, dossier_audio))
