import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts'

export default function TxnVelocityChart({ data }) {
  return (
    <div className="border border-slate-800 rounded-xl bg-slate-900/20 p-3">
      <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">TXN Velocity · 12h</div>
      <ResponsiveContainer width="100%" height={160}>
        <LineChart data={data} margin={{top:0,right:8,left:-20,bottom:0}}>
          <XAxis dataKey="time" tick={{fontSize:8, fill:'#475569'}} tickLine={false} interval={3} />
          <YAxis tick={{fontSize:8, fill:'#475569'}} tickLine={false} axisLine={false} />
          <Tooltip
            contentStyle={{background:'#0f172a', border:'1px solid #1e293b', fontSize:'10px', borderRadius:'6px'}}
            labelStyle={{color:'#94a3b8'}}
          />
          <Line type="monotone" dataKey="Mumbai"    stroke="#22d3ee" strokeWidth={1.5} dot={false} />
          <Line type="monotone" dataKey="Delhi"     stroke="#a78bfa" strokeWidth={1.5} dot={false} />
          <Line type="monotone" dataKey="Bangalore" stroke="#34d399" strokeWidth={1.5} dot={false} />
          <Line type="monotone" dataKey="Chennai"   stroke="#fb923c" strokeWidth={1.5} dot={false} />
          <Legend wrapperStyle={{fontSize:'9px', paddingTop:'4px'}} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
