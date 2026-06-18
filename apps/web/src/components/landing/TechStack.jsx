const STACK = [
  { category: 'AI Models', items: ['Qwen2-VL 72B', 'Llama 3.3 70B', 'GOT-OCR2.0', 'BGE-M3', 'Siamese SNN', 'XGBoost'] },
  { category: 'Inference', items: ['vLLM', 'Langfuse', 'SHAP', 'MLflow', 'GPU A100 80GB'] },
  { category: 'Workflows', items: ['Temporal', 'Kafka (Strimzi)', 'KEDA', 'Exactly-once'] },
  { category: 'Data', items: ['YugabyteDB', 'Redis Cluster', 'MinIO WORM', 'Immudb', 'pgvector'] },
  { category: 'Platform', items: ['Kubernetes', 'Istio mTLS', 'ArgoCD', 'HashiCorp Vault', 'OPA'] },
  { category: 'Observability', items: ['OpenTelemetry', 'Prometheus', 'Grafana', 'Loki', 'Tempo'] },
]

export default function TechStack() {
  return (
    <section className="py-20 px-6 border-t border-white/5">
      <div className="max-w-7xl mx-auto">
        <div className="text-center mb-12">
          <h2 className="text-2xl font-bold text-white mb-3">Built on Proven Open-Source</h2>
          <p className="text-slate-400 text-sm max-w-lg mx-auto">
            No proprietary lock-in. Every component is open-source or Apache 2.0 licensed.
            100% on-premises — no cloud vendor dependencies.
          </p>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
          {STACK.map(({ category, items }) => (
            <div key={category} className="glass rounded-xl p-4">
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">{category}</div>
              <div className="space-y-1.5">
                {items.map(item => (
                  <div key={item} className="text-xs text-slate-300 flex items-center gap-1.5">
                    <span className="w-1 h-1 rounded-full bg-slate-600 flex-shrink-0" />
                    {item}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
