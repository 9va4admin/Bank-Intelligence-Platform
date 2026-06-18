export default function FleetFilter({ filters, setFilters, states, cities }) {
  return (
    <div className="flex items-center gap-3 border border-slate-800 rounded-lg bg-slate-900/40 px-4 py-2">
      <span className="text-xs text-slate-500 uppercase tracking-wider shrink-0">Filter:</span>

      <select
        value={filters.state}
        onChange={e => setFilters(f => ({ ...f, state: e.target.value, city: '' }))}
        className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-cyan-600"
      >
        <option value="">All States</option>
        {states.map(s => <option key={s}>{s}</option>)}
      </select>

      <select
        value={filters.city}
        onChange={e => setFilters(f => ({ ...f, city: e.target.value }))}
        className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-cyan-600"
      >
        <option value="">All Cities</option>
        {cities.map(c => <option key={c}>{c}</option>)}
      </select>

      <input
        value={filters.search}
        onChange={e => setFilters(f => ({ ...f, search: e.target.value }))}
        placeholder="Search ATM ID..."
        className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 font-mono placeholder-slate-600 focus:outline-none focus:border-cyan-600 w-40"
      />

      {(filters.state || filters.city || filters.search) && (
        <button
          onClick={() => setFilters({ state:'', city:'', branch:'', search:'' })}
          className="text-xs text-cyan-500 hover:text-cyan-300 transition-colors"
        >
          ✕ Clear
        </button>
      )}

      <span className="ml-auto text-xs text-slate-600 font-mono">
        Filter to inspect individual branches and risk zones
      </span>
    </div>
  )
}
