# VAIVOX - Audit Fix Tasks

Liste de taches issue de l'audit du depot. L'objectif est de transformer l'etat actuel
(bon socle technique, pas encore pret pour une release publique complete) en release
end-user robuste.

Note de suivi: les cases cochees ici correspondent aux corrections realisables dans le
depot et couvertes par code/tests/docs/CI. Les cases qui restent ouvertes demandent soit
un environnement externe (VoiceAttack, DCS, VAICOM reel, machine propre), soit un chantier
fonctionnel plus large que le durcissement d'audit traite dans ce passage.

## P0 - Bloquants release publique

- [x] Packager une release complete VAIVOX.
  - Inclure `VAIVOX.exe`, `_internal/`, les assets/configs, `README_FIRST.txt`, le profil
    `VAIVOX - VA Profile.vap`, et `VaivoxVAPlugin.dll`.
  - Ajouter une structure claire dans le zip, par exemple `VoiceAttack/Apps/VAIVOX/`.
  - Critere d'acceptation: un utilisateur peut extraire le zip et trouver tous les
    artefacts necessaires sans compiler le plugin.

- [x] Integrer ou distribuer le generateur VAICOM avec le build gele.
  - Ne plus dependre de `tools/` absent dans PyInstaller pour la generation automatique.
  - Option recommandee: migrer le generateur dans `src/vaivox/infrastructure/vocabulary/`
    ou l'embarquer explicitement dans `build_exe.ps1`.
  - Critere d'acceptation: dans une release PyInstaller, le refresh vocabulaire ne renvoie
    plus `generator unavailable` quand une installation VAICOM valide existe.

- [ ] Faire le smoke end-to-end VoiceAttack + VAICOM + DCS.
  - Tester une commande connue: declenchement in-game, `matched=true`, telemetry, usage hit.
  - Tester une commande inconnue: `matched=false`, near-miss en telemetry, pas de stamp usage.
  - Critere d'acceptation: recette documentee avec captures/logs ou notes de resultat.

- [ ] Re-pointer et valider le profil VoiceAttack.
  - Importer `VAIVOX - VA Profile.vap`.
  - Re-pointer les actions "Execute an external plugin function" vers le plugin VAIVOX.
  - Critere d'acceptation: `Start VAIVOX Recording` et `Stop VAIVOX Recording` pilotent
    bien le serveur depuis VoiceAttack.

- [x] Aligner les versions produit.
  - Harmoniser `pyproject.toml`, `src/vaivox/__init__.py`, `build_exe.ps1` et le nom du zip.
  - Critere d'acceptation: une seule version canonique apparait dans l'app, les logs, le
    package Python et la release.

## P1 - Securite et confidentialite

- [x] Redacter la configuration avant logging.
  - Remplacer le log de config brute par `get_safe_configuration()` dans
    `src/vaivox/infrastructure/config/settings.py`.
  - Ajouter un test verifiant qu'une cle `*_api_key`, `token`, `secret` ou `password` n'est
    jamais loggee en clair.
  - Critere d'acceptation: aucun secret present dans `VAIVOX.log` meme si l'utilisateur le
    met par erreur dans `settings.cfg`.

- [x] Durcir les sockets locaux.
  - Garder `127.0.0.1` par defaut et refuser/documenter explicitement les binds non locaux.
  - Ajouter une option de token/nonce local pour les commandes sensibles, ou au minimum un
    avertissement fort si `control_host` ou `voiceattack_host` sort de localhost.
  - Critere d'acceptation: un bind reseau accidentel ne transforme pas VAIVOX en controle
    distant non authentifie.

- [x] Ajouter des limites de taille aux payloads HTTP API.
  - Limiter `Content-Length` sur les POST introspection.
  - Retourner `413 Payload Too Large` au-dela de la limite.
  - Critere d'acceptation: un client local ne peut pas faire consommer une memoire arbitraire
    via `/reconcile/dry-run` ou `/reconcile/simulate`.

- [x] Revoir la politique telemetry par defaut.
  - Confirmer que le texte transcrit stocke localement est acceptable par defaut.
  - Ajouter un message UI/README clair: la telemetry contient les utterances.
  - Critere d'acceptation: l'utilisateur comprend ou desactive `telemetry_enabled`.

## P1 - Robustesse runtime

- [x] Rendre `TkStatusWriter` thread-safe.
  - Ne plus ecrire directement dans Tk depuis les threads tray/control server/API/refresh.
  - Passer par `window.after(...)` ou une queue UI consommee par le thread Tk.
  - Critere d'acceptation: tous les `StatusReporter.report()` appeles hors thread UI sont
    marshales vers le thread Tk.

- [x] Corriger le crash kneeboard sur mot trop long.
  - Gerer le cas `current_words == []` avant `justify_line(...)`.
  - Decider une strategie: ne pas couper, couper proprement, ou hard-wrap les mots longs.
  - Ajouter un test avec un mot plus long que `text_line_length`.
  - Critere d'acceptation: `format_for_dcs_kneeboard("supercalifragilistic...", 10)` ne
    leve plus d'exception.

- [x] Proteger `SoundDeviceRecorder.stop()`.
  - Gerer les appels stop quand `_stream` ou `_wave_file` est `None`.
  - Garantir la fermeture partielle en cas d'erreur dans `start()`.
  - Critere d'acceptation: un echec micro/audio ne laisse pas l'app dans un etat recording
    incoherent.

- [x] Valider proprement les entiers de config critiques.
  - Utiliser `get_int_setting()` ou equivalent pour `voiceattack_port` et
    `text_line_length`.
  - Ajouter bornes et fallback pour les ports, timeouts, line length.
  - Critere d'acceptation: une mauvaise valeur utilisateur ne crash pas le demarrage.

- [x] Corriger la fermeture plugin C#.
  - Eviter `_listener.Stop()` si `_listener == null`.
  - Gerer proprement `ObjectDisposedException` dans la boucle `AcceptTcpClientAsync`.
  - Critere d'acceptation: quitter VoiceAttack sans serveur/app active ne provoque pas
    d'erreur rouge inutile.

## P2 - Tests et qualite

- [x] Ajouter des tests unitaires pour les adaptateurs faibles en couverture.
  - Cibles prioritaires: UI writer, kneeboard, control socket, audio recorder.
  - Critere d'acceptation: les chemins d'erreur principaux sont couverts sans dependances
    materielles.

- [x] Ajouter un test packaging minimal.
  - Lancer `build_exe.ps1 -Profile api -Clean` en job Windows, ou au moins verifier la
    presence des artefacts attendus apres packaging.
  - Critere d'acceptation: CI echoue si le zip release manque l'exe, les assets, le plugin,
    l'installateur VoiceAttack ou le profil.

- [x] Ajouter un test de build plugin C# en CI Windows.
  - Executer `dotnet build plugin/VaivoxVAPlugin/VaivoxVAPlugin.csproj -c Release`.
  - Critere d'acceptation: le plugin ne peut plus casser sans etre detecte.

- [x] Ajouter un smoke API introspection avec limites.
  - Tester 401 token, 403 actions desactivees, 413 payload trop large, 400 JSON invalide.
  - Critere d'acceptation: comportement stable et documente sur les cas abusifs.

- [x] Ajouter un audit dependances automatise.
  - Executer `pip-audit` sur les deps exportees avec extras/groupes.
  - Executer `dotnet list package --vulnerable --include-transitive`.
  - Critere d'acceptation: la CI signale les CVE connues avant release.

## P2 - Fonctionnel reconciliation/vocabulaire

- [ ] Faire le test end-to-end du generateur VAICOM sur une vraie installation.
  - Verifier `vaicom_keyterms.txt` et `phrase_index.txt`.
  - Comparer les phrases generees aux commandes VoiceAttack reelles.
  - Critere d'acceptation: le snapper ameliore les matchs sans casser `wrong_match == 0`.

- [ ] Brancher la pipeline sur `VocabularyRepository`.
  - Remplacer progressivement les lectures directes `config.get_word_mappings()` /
    `get_fuzzy_words()` par une source structuree.
  - Critere d'acceptation: la gouvernance JSONL devient la source de verite runtime.

- [ ] Activer la maintenance LRU vocabulary.
  - Appeler `VocabularyGovernor.govern()` dans une passe de maintenance.
  - Persister via `VocabularyRepository.replace_entries()`.
  - Critere d'acceptation: les entrees learned peuvent etre evincees sans toucher les
    entrees default.

- [ ] Ajouter le rapport offline de near-misses.
  - Lire `telemetry.jsonl`.
  - Regrouper les not-found/abstains frequents.
  - Proposer mappings/aliases candidats sans les appliquer automatiquement.
  - Critere d'acceptation: un utilisateur peut reviser les echecs frequents apres session.

- [ ] Implementer l'attribution Tier 2.
  - Rejouer la pipeline avec oracle phrase-index pour les cas ambigus.
  - Critere d'acceptation: les hits vocabulary creditent l'edition exacte, pas seulement
    la presence surface-form.

## P3 - Documentation et experience utilisateur

- [x] Mettre a jour `README_FIRST.txt`.
  - Mentionner explicitement plugin DLL, profil `.vap`, re-point VoiceAttack, logs,
    telemetry, API keys.
  - Critere d'acceptation: le quick start release couvre toute la chaine VoiceAttack.

- [x] Mettre a jour le README principal.
  - Retirer/clarifier les passages encore herites WhisperAttack/GPU si la release API est
    le chemin par defaut.
  - Corriger les instructions qui supposent des fichiers absents du zip.
  - Critere d'acceptation: les instructions correspondent exactement a l'artefact genere.

- [x] Ajouter une page "Security model".
  - Expliquer sockets localhost, API introspection, tokens, telemetry locale, secrets env.
  - Critere d'acceptation: les limites de securite sont explicites avant publication.

- [x] Documenter la procedure release.
  - Ordre recommande: gates Python, build C#, build PyInstaller, audit deps, smoke runtime,
    zip/signature/checksum.
  - Critere d'acceptation: une release est reproductible par une autre personne.

- [ ] Confirmer la licence/provenance VAICOM.
  - Valider le choix "generate locally, do not redistribute derived data".
  - Critere d'acceptation: la posture ADR-0005 est juridiquement/documentairement solide.

## Definition of Done globale

- [x] `uv run ruff check .`
- [x] `uv run ruff format --check .`
- [x] `uv run mypy`
- [x] `uv run lint-imports --config pyproject.toml --no-cache`
- [x] `uv run pytest --cov=vaivox`
- [x] `dotnet build plugin/VaivoxVAPlugin/VaivoxVAPlugin.csproj -c Release`
- [x] `build_exe.ps1 -Profile api -Clean`
- [x] Audit dependances Python + NuGet sans vulnerabilites connues.
- [ ] Smoke VoiceAttack + VAICOM + DCS documente.
- [ ] Zip release complet verifie sur une machine propre.
