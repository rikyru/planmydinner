import { defineComponent } from 'vue';

/**
 * Vista Storico: diario settimanale con kcal/macro per giorno
 * (dati da /integration/summary) e pasti dal piano salvato.
 */
const HistoryView = defineComponent({
    name: 'HistoryView',
    inject: ['toast'],
    template: `
        <div class="history-view">
            <h2>Storico</h2>

            <div class="card" style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
                <button @click="shiftWeek(-7)" class="btn-secondary">‹</button>
                <strong style="min-width:170px;text-align:center;">{{ rangeLabel }}</strong>
                <button @click="shiftWeek(7)" class="btn-secondary" :disabled="isCurrentWeek">›</button>
                <button v-if="!isCurrentWeek" @click="goToday" class="btn-today">Questa settimana</button>
                <button @click="openTargets" class="btn-sm btn-secondary" style="margin-left:auto;">🎯 Obiettivi</button>
            </div>

            <div v-if="loading" class="loading">Caricamento...</div>

            <template v-if="!loading && summary">
                <!-- Riepilogo periodo (vs obiettivo se impostato) -->
                <div class="hist-stats">
                    <div v-for="t in statTiles" :key="t.key" class="hist-stat">
                        <span class="hist-stat__value">{{ t.value }}</span>
                        <span class="hist-stat__label">{{ t.label }}</span>
                        <span v-if="t.target" class="hist-stat__target">obiettivo {{ t.target }}</span>
                        <span v-if="t.delta !== null" class="hist-stat__delta" :class="t.deltaClass">{{ t.delta }}</span>
                    </div>
                    <div class="hist-stat">
                        <span class="hist-stat__value">{{ Math.round((summary.adherence.adherence_score || 0) * 100) }}%</span>
                        <span class="hist-stat__label">aderenza</span>
                    </div>
                </div>

                <!-- Grafico kcal per giorno -->
                <div class="card">
                    <div style="font-size:13px;font-weight:600;color:var(--text-2);margin-bottom:10px;">kcal per giorno</div>
                    <div class="hist-chart" style="position:relative;">
                        <div v-if="kcalTarget" class="hist-target-line" :style="{bottom: targetLinePct + '%'}"
                             :title="'Obiettivo: ' + kcalTarget + ' kcal'"></div>
                        <div v-for="d in summary.days" :key="d.date" class="hist-col"
                             :title="barTitle(d)" @click="scrollToDay(d.date)">
                            <div class="hist-bar" :class="{'hist-bar--empty': !d.nutrition, 'hist-bar--partial': d.nutrition && !d.complete, 'hist-bar--estimated': d.has_estimated_meal, 'hist-bar--today': d.date === today}"
                                 :style="{height: barHeight(d) + '%'}"></div>
                            <span class="hist-day" :class="{'hist-day--today': d.date === today}">{{ dayInitial(d.date) }}</span>
                        </div>
                    </div>
                </div>

                <!-- Diario per giorno -->
                <div v-for="d in summary.days" :key="'card-' + d.date" class="card hist-daycard" :id="'hist-' + d.date">
                    <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;">
                        <strong style="text-transform:capitalize;">{{ dayLabel(d.date) }}</strong>
                        <span v-if="d.nutrition" class="hint">
                            {{ Math.round(d.nutrition.kcal) }} kcal ·
                            P {{ Math.round(d.nutrition.protein_g) }}g ·
                            C {{ Math.round(d.nutrition.carbs_g) }}g ·
                            G {{ Math.round(d.nutrition.fat_g) }}g
                            <template v-if="!d.complete">(parziale)</template>
                            <template v-else-if="d.has_estimated_meal">(≈ stima AI)</template>
                        </span>
                        <span v-if="d.free_meals" class="meal-badge meal-badge--free"
                              :title="d.has_estimated_meal ? 'Kcal stimate dalla descrizione (AI)' : 'Calorie sconosciute: giorno escluso dalle medie'">
                            🎉 libero{{ d.has_estimated_meal ? ' ≈' : '' }}
                        </span>
                        <span v-if="d.not_eaten" class="meal-badge meal-badge--not-eaten">✗ saltato</span>
                    </div>
                    <div v-if="mealsFor(d.date).length" style="margin-top:8px;display:flex;flex-direction:column;gap:4px;">
                        <div v-for="m in mealsFor(d.date)" :key="m.meal_type" style="display:flex;gap:8px;font-size:13.5px;align-items:baseline;">
                            <span style="min-width:52px;font-size:10.5px;font-weight:700;color:var(--text-3);text-transform:uppercase;">
                                {{ m.meal_type }}
                            </span>
                            <span>{{ m.name }}</span>
                        </div>
                    </div>
                    <div v-else class="hint" style="margin-top:6px;">Nessun pasto pianificato.</div>
                </div>
            </template>

            <!-- Modal obiettivi giornalieri -->
            <div v-if="targetsOpen" class="modal-overlay" @click.self="targetsOpen = false">
                <div class="modal">
                    <h3>🎯 Obiettivi giornalieri</h3>
                    <p class="hint" style="margin:0 0 12px;">
                        Valori indicativi al giorno. Compaiono nello Storico e nella API per OpenFit.
                    </p>
                    <div class="custom-form">
                        <label>kcal / giorno</label>
                        <input v-model.number="targetForm.kcal" type="number" min="0" step="50" placeholder="es. 2200">
                        <label>Proteine (g)</label>
                        <input v-model.number="targetForm.protein_g" type="number" min="0" step="5" placeholder="es. 120">
                        <label>Carboidrati (g)</label>
                        <input v-model.number="targetForm.carbs_g" type="number" min="0" step="10" placeholder="es. 250">
                        <label>Grassi (g)</label>
                        <input v-model.number="targetForm.fat_g" type="number" min="0" step="5" placeholder="es. 70">
                    </div>
                    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;">
                        <button @click="suggestFromPlan" class="btn-secondary btn-sm" :disabled="suggesting">
                            {{ suggesting ? '…' : '📋 Dal piano della nutrizionista' }}
                        </button>
                        <button v-if="summary?.averages" @click="suggestTargets" class="btn-secondary btn-sm">
                            📈 Dalle medie di questo periodo
                        </button>
                    </div>
                    <div style="display:flex;gap:10px;margin-top:14px;">
                        <button @click="saveTargets" class="btn-primary" :disabled="savingTargets">
                            {{ savingTargets ? 'Salvataggio…' : '💾 Salva' }}
                        </button>
                        <button @click="targetsOpen = false" class="btn-secondary">Annulla</button>
                    </div>
                </div>
            </div>
        </div>
    `,
    data() {
        const today = new Date().toISOString().slice(0, 10);
        const d = new Date(today + 'T12:00:00');
        const monday = new Date(d);
        monday.setDate(d.getDate() - ((d.getDay() + 6) % 7));
        return {
            today,
            start: monday.toISOString().slice(0, 10),
            profiles: [],
            summary: null,
            planMeals: {},   // date -> [{meal_type, name}]
            loading: false,
            targetsOpen: false,
            targetForm: { kcal: null, protein_g: null, carbs_g: null, fat_g: null },
            savingTargets: false,
            suggesting: false,
        };
    },
    computed: {
        end() {
            const d = new Date(this.start + 'T12:00:00');
            d.setDate(d.getDate() + 6);
            return d.toISOString().slice(0, 10);
        },
        rangeLabel() {
            const fmt = s => new Date(s + 'T12:00:00').toLocaleDateString('it-IT', { day: 'numeric', month: 'short' });
            return `${fmt(this.start)} — ${fmt(this.end)}`;
        },
        isCurrentWeek() { return this.start <= this.today && this.today <= this.end; },
        maxKcal() {
            const vals = (this.summary?.days || []).map(d => d.nutrition?.kcal || 0);
            return Math.max(1, ...vals, this.kcalTarget || 0);
        },
        kcalTarget() { return this.summary?.targets?.kcal || null; },
        targetLinePct() {
            // il grafico riserva ~24px in basso alle etichette: riporto la quota
            // della linea alla sola area delle barre (130px totali, ~106 utili)
            return Math.min(96, Math.round((this.kcalTarget / this.maxKcal) * (106 / 130) * 100) + 18);
        },
        statTiles() {
            const avg = this.summary?.averages;
            const targets = this.summary?.targets || {};
            const defs = [
                { key: 'kcal',      label: 'kcal / giorno', unit: '' },
                { key: 'protein_g', label: 'proteine',      unit: 'g' },
                { key: 'carbs_g',   label: 'carboidrati',   unit: 'g' },
                { key: 'fat_g',     label: 'grassi',        unit: 'g' },
            ];
            return defs.map(d => {
                const value = avg ? Math.round(avg[d.key]) : null;
                const target = targets[d.key] ? Math.round(targets[d.key]) : null;
                let delta = null, deltaClass = '';
                if (value !== null && target) {
                    const pct = Math.round(((value - target) / target) * 100);
                    delta = (pct > 0 ? '+' : '') + pct + '%';
                    deltaClass = Math.abs(pct) <= 10 ? 'delta-ok' : (Math.abs(pct) <= 25 ? 'delta-warn' : 'delta-bad');
                }
                return {
                    key: d.key,
                    label: d.label,
                    value: value !== null ? value + d.unit : '—',
                    target: target ? target + d.unit : null,
                    delta, deltaClass,
                };
            });
        },
    },
    mounted() { this.init(); },
    methods: {
        async init() {
            try {
                const resp = await window.apiFetch('/profiles/');
                this.profiles = resp.ok ? await resp.json() : [];
            } catch (_) { this.profiles = []; }
            await this.load();
        },
        async load() {
            if (!this.profiles.length) return;
            this.loading = true;
            try {
                const pid = this.profiles[0].id;
                const params = new URLSearchParams({ profile_id: pid, start_date: this.start, end_date: this.end });
                const resp = await window.apiFetch('/integration/summary?' + params);
                this.summary = resp.ok ? await resp.json() : null;
                await this.loadPlanMeals(pid);
            } catch (e) {
                this.toast.add('Errore nel caricamento: ' + e.message, 'error');
            } finally {
                this.loading = false;
            }
        },
        async loadPlanMeals(pid) {
            // Mappa date -> pasti dal piano salvato; i piani sono finestre rolling,
            // quindi al massimo servono un paio di fetch per coprire la settimana.
            this.planMeals = {};
            const fetchFor = async (dateStr) => {
                try {
                    const params = new URLSearchParams({ profile_id_A: pid, target_date: dateStr });
                    const resp = await window.apiFetch('/planner/plan-for-date?' + params);
                    if (!resp.ok) return;
                    const plan = await resp.json();
                    for (const day of plan?.daily_plans || []) {
                        this.planMeals[day.date] = (day.meals || [])
                            .filter(m => m.items?.length)
                            .map(m => ({ meal_type: m.meal_type, name: m.items[0].item_name }));
                    }
                } catch (_) { /* giorno senza piano */ }
            };
            await fetchFor(this.start);
            for (const d of this.summary?.days || []) {
                if (!(d.date in this.planMeals)) { await fetchFor(d.date); break; }
            }
        },
        shiftWeek(days) {
            const d = new Date(this.start + 'T12:00:00');
            d.setDate(d.getDate() + days);
            this.start = d.toISOString().slice(0, 10);
            this.load();
        },
        goToday() {
            const d = new Date(this.today + 'T12:00:00');
            d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
            this.start = d.toISOString().slice(0, 10);
            this.load();
        },
        barHeight(d) {
            if (!d.nutrition) return 4;
            return Math.max(6, Math.round((d.nutrition.kcal / this.maxKcal) * 100));
        },
        barTitle(d) {
            const label = this.dayLabel(d.date);
            if (!d.nutrition) return `${label}: nessun dato`;
            const n = d.nutrition;
            const base = `${Math.round(n.kcal)} kcal — P ${Math.round(n.protein_g)}g · C ${Math.round(n.carbs_g)}g · G ${Math.round(n.fat_g)}g`;
            if (!d.complete) return `${label}: ${base} (parziale — pasto libero non stimato, escluso dalle medie)`;
            if (d.has_estimated_meal) return `${label}: ${base} (include una stima AI per il pasto libero)`;
            return `${label}: ${base}`;
        },
        dayInitial(dateStr) {
            return new Date(dateStr + 'T12:00:00').toLocaleDateString('it-IT', { weekday: 'short' }).slice(0, 3);
        },
        dayLabel(dateStr) {
            return new Date(dateStr + 'T12:00:00').toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'short' });
        },
        mealsFor(dateStr) { return this.planMeals[dateStr] || []; },
        openTargets() {
            const t = this.summary?.targets || {};
            this.targetForm = {
                kcal: t.kcal || null, protein_g: t.protein_g || null,
                carbs_g: t.carbs_g || null, fat_g: t.fat_g || null,
            };
            this.targetsOpen = true;
        },
        suggestTargets() {
            const a = this.summary.averages;
            this.targetForm = {
                kcal: Math.round(a.kcal / 50) * 50,
                protein_g: Math.round(a.protein_g / 5) * 5,
                carbs_g: Math.round(a.carbs_g / 5) * 5,
                fat_g: Math.round(a.fat_g / 5) * 5,
            };
        },
        async suggestFromPlan() {
            this.suggesting = true;
            try {
                const params = new URLSearchParams({ profile_id: this.profiles[0].id });
                const resp = await window.apiFetch('/integration/plan-targets?' + params);
                const data = resp.ok ? await resp.json() : null;
                if (!data?.targets) {
                    this.toast.add(data?.detail || 'Nessun piano da cui derivare gli obiettivi.', 'info');
                    return;
                }
                const t = data.targets;
                this.targetForm = {
                    kcal: Math.round(t.kcal / 50) * 50,
                    protein_g: Math.round(t.protein_g / 5) * 5,
                    carbs_g: Math.round(t.carbs_g / 5) * 5,
                    fat_g: Math.round(t.fat_g / 5) * 5,
                };
                this.toast.add('Obiettivi derivati dal piano (media dei giorni pianificati).', 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            } finally {
                this.suggesting = false;
            }
        },
        async saveTargets() {
            this.savingTargets = true;
            try {
                const targets = {};
                for (const k of ['kcal', 'protein_g', 'carbs_g', 'fat_g']) {
                    if (this.targetForm[k] > 0) targets[k] = this.targetForm[k];
                }
                const pid = this.profiles[0].id;
                const resp = await window.apiFetch('/planner/rules/' + encodeURIComponent(pid), {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ nutrition_targets: targets }),
                });
                if (!resp.ok) throw new Error(await resp.text());
                this.toast.add('Obiettivi salvati!', 'success');
                this.targetsOpen = false;
                await this.load();
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            } finally {
                this.savingTargets = false;
            }
        },
        scrollToDay(dateStr) {
            document.getElementById('hist-' + dateStr)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        },
    },
});

export default HistoryView;
