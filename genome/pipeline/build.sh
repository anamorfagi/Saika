#!/bin/bash
# Полная сборка артефакта из исходного HTML. Запуск: bash build.sh
set -e
cp /root/.claude/projects/-home-claude/43436c30-0260-5fdd-90c5-d0cd24a7a16c/tool-results/artifact-14935dd7-1789443491-1bdc.html gs.html
for s in update_v11 update_v11b update_voice update_ui update_mind update_anime update_fam5 update_trace update_sig update_nat update_sk; do node $s.js >/dev/null || { echo FAIL $s; exit 1; }; if [ $s = update_v11 ] || [ $s = update_v11b ]; then cp gs.html genome-studio.html; fi; done
node pipeline/build_char.js || exit 1
for s in update_gender update_gender2 update_norms update_age update_nat2 update_api update_observe update_newchar update_share update_forms update_kinds update_brand update_sharefs; do node $s.js >/dev/null || { echo FAIL $s; exit 1; }; done
node pipeline/export_all.js dist/AnamorfGenom >/dev/null || exit 1
node update_store.js >/dev/null || exit 1; node update_des2.js || exit 1; node pipeline/sigs_dump.js gs.html >/dev/null || exit 1
for s in update_newcard update_archtyp update_slider update_zoom update_mix update_persona update_scout update_ingest update_comp update_behavior update_comp2 update_voice2 update_dna update_helix2 update_bins update_axis update_strip update_desc2 update_facets2 update_legend update_compact update_tail update_head update_head2 update_zones update_fit update_archlit update_priors update_cards update_ava2 update_traceby update_seedcard update_live; do node $s.js >/dev/null || { echo FAIL $s; exit 1; }; done
node update_comp3.js || exit 1
node update_research.js || exit 1
node update_conn.js || exit 1
node update_keys.js || exit 1
node update_avakeep.js || exit 1
node update_avapush.js || exit 1
node update_avahard.js || exit 1
node update_avaread.js || exit 1
node update_genre.js || exit 1
node update_beast.js || exit 1
node update_natplus.js || exit 1
node update_sex.js || exit 1
node update_stub.js || exit 1
node update_tofile.js || exit 1
node update_prompt.js || exit 1
node update_smith.js || exit 1
node update_reload.js || exit 1
node update_arch.js || exit 1
node update_agecanon.js || exit 1
cp gs.html genome-studio.html; echo built $(stat -c %s genome-studio.html)
