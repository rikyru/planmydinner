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
            </div>

            <div v-if="loading" class="loading">Caricamento...</div>

            <template v-if="!loading && summary">
                <!-- Riepilogo periodo -->
                <div class="hist-stats">
                    <div class="hist-stat">
                        <span class="hist-stat__value">{{ summary.averages ? Math.round(summary.averages.kcal) : '—' }}</span>
                        <span class="hist-stat__label">kcal / giorno</span>
                    </div>
                    <div class="hist-stat">
                        <span class="hist-stat__value">{{ summary.averages ? Math.round(summary.averages.protein_g) + 'g' : '—' }}</span>
                        <span class="hist-stat__label">proteine</span>
                    </div>
                    <div class="hist-stat">
                        <span class="hist-stat__value">{{ summary.averages ? Math.round(summary.averages.carbs_g) + 'g' : '—' }}</span>
                        <span class="hist-stat__label">carboidrati</span>
                    </div>
                    <div class="hist-stat">
                        <span class="hist-stat__value">{{ summary.averages ? Math.round(summary.averages.fat_g) + 'g' : '—' }}</span>
                        <span class="hist-stat__label">grassi</span>
                    </div>
                    <div class="hist-stat">
                        <span class="hist-stat__value">{{ Math.round((summary.adherence.adherence_score || 0) * 100) }}%</span>
                        <span class="hist-stat__label">aderenza</span>
                    </div>
                </div>

                <!-- Grafico kcal per giorno -->
                <div class="card">
                    <div style="font-size:13px;font-weight:600;color:var(--text-2);margin-bottom:10px;">kcal per giorno</div>
                    <div class="hist-chart">
                        <div v-for="d in summary.days" :key="d.date" class="hist-col"
                             :title="barTitle(d)" @click="scrollToDay(d.date)">
                            <div class="hist-bar" :class="{'hist-bar--empty': !d.nutrition, 'hist-bar--today': d.date === today}"
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
                        </span>
                        <span v-if="d.free_meals" class="meal-badge meal-badge--free">🎉 libero</span>
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
            return Math.max(1, ...vals);
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
            return `${label}: ${Math.round(n.kcal)} kcal — P ${Math.round(n.protein_g)}g · C ${Math.round(n.carbs_g)}g · G ${Math.round(n.fat_g)}g`;
        },
        dayInitial(dateStr) {
            return new Date(dateStr + 'T12:00:00').toLocaleDateString('it-IT', { weekday: 'short' }).slice(0, 3);
        },
        dayLabel(dateStr) {
            return new Date(dateStr + 'T12:00:00').toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'short' });
        },
        mealsFor(dateStr) { return this.planMeals[dateStr] || []; },
        scrollToDay(dateStr) {
            document.getElementById('hist-' + dateStr)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        },
    },
});

export default HistoryView;
