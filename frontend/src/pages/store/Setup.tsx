/**
 * Setup.tsx — Onboarding wizard for new stores
 *
 * Shows a step-by-step checklist to help new store owners configure
 * their bot quickly. Each step has a status (done/pending) and a
 * direct action button.
 *
 * Progress is tracked from live API data + localStorage flags for
 * steps we can't detect automatically (widget install, bot test).
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Spinner } from '@heroui/react'
import { api, StoreInfo } from '../../api'

function Icon({ paths, size = 18, className = '' }: {
  paths: string | string[]; size?: number; className?: string
}) {
  const arr = Array.isArray(paths) ? paths : [paths]
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={2} strokeLinecap="round"
      strokeLinejoin="round" className={className}>
      {arr.map((d, i) => <path key={i} d={d} />)}
    </svg>
  )
}

interface SetupState {
  aiConfigured:  boolean
  productsSynced: boolean
  widgetInstalled: boolean
  botTested:      boolean
}

interface Props { storeId: string; store: StoreInfo }

export default function Setup({ storeId, store }: Props) {
  const navigate = useNavigate()
  const [state, setState]   = useState<SetupState>({
    aiConfigured: false, productsSynced: false,
    widgetInstalled: false, botTested: false,
  })
  const [loading, setLoading]   = useState(true)
  const [syncing, setSyncing]   = useState(false)
  const [dismissed, setDismissed] = useState(false)

  // Persistent flags (steps we can't detect from API)
  const widgetKey = `setup_widget_${storeId}`
  const testKey   = `setup_tested_${storeId}`
  const dimKey    = `setup_dismissed_${storeId}`

  useEffect(() => {
    if (localStorage.getItem(dimKey) === '1') { setDismissed(true); return }
    load()
  }, [storeId])

  async function load() {
    setLoading(true)
    try {
      const [ai, info] = await Promise.all([
        api.getAI(storeId).catch(() => null),
        api.getStoreInfo(storeId).catch(() => store),
      ])
      setState({
        aiConfigured:    ai?.provider !== 'env' && !!ai?.provider,
        productsSynced:  (info?.products_count ?? 0) > 0 && info?.last_sync !== 'never',
        widgetInstalled: localStorage.getItem(widgetKey) === '1',
        botTested:       localStorage.getItem(testKey)   === '1',
      })
    } finally { setLoading(false) }
  }

  function markWidget() {
    localStorage.setItem(widgetKey, '1')
    setState(s => ({ ...s, widgetInstalled: true }))
  }
  function markTested() {
    localStorage.setItem(testKey, '1')
    setState(s => ({ ...s, botTested: true }))
  }
  function dismiss() {
    localStorage.setItem(dimKey, '1')
    setDismissed(true)
  }

  async function handleSync() {
    setSyncing(true)
    try {
      await api.sync(storeId)
      setState(s => ({ ...s, productsSynced: true }))
    } catch { /* ignore */ } finally { setSyncing(false) }
  }

  const steps = [
    {
      id: 'ai',
      icon: ['M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z'],
      title: 'إعداد مزوّد الذكاء الاصطناعي',
      desc: 'أضف مفتاح Groq أو Anthropic أو OpenAI لتشغيل البوت.',
      done: state.aiConfigured,
      action: () => navigate(`/store/${storeId}/settings`),
      label: 'فتح الإعدادات',
      color: { ring: 'ring-violet-500/40', bg: 'bg-violet-500/10', text: 'text-violet-400', doneBg: 'bg-violet-500/20' },
    },
    {
      id: 'sync',
      icon: ['M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15'],
      title: 'مزامنة منتجات المتجر',
      desc: 'البوت يحتاج قائمة المنتجات ليتعرف عليها ويجيب عنها.',
      done: state.productsSynced,
      action: handleSync,
      label: syncing ? 'جاري المزامنة...' : 'مزامنة الآن',
      loading: syncing,
      color: { ring: 'ring-cyan-500/40', bg: 'bg-cyan-500/10', text: 'text-cyan-400', doneBg: 'bg-cyan-500/20' },
    },
    {
      id: 'widget',
      icon: ['M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4'],
      title: 'تثبيت الويدجت في المتجر',
      desc: 'أضف كود البوت لمتجرك على سلة عبر Salla Snippets.',
      done: state.widgetInstalled,
      action: () => {
        window.open('/snippet', '_blank')
        markWidget()
      },
      label: 'عرض كود التثبيت',
      color: { ring: 'ring-teal-500/40', bg: 'bg-teal-500/10', text: 'text-teal-400', doneBg: 'bg-teal-500/20' },
    },
    {
      id: 'test',
      icon: ['M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z'],
      title: 'اختبر البوت مع عميل حقيقي',
      desc: 'افتح صفحة الاختبار وتحدث مع البوت للتأكد من أنه يعمل.',
      done: state.botTested,
      action: () => {
        window.open(`/test-widget/${storeId}`, '_blank')
        markTested()
      },
      label: 'بدء الاختبار',
      color: { ring: 'ring-emerald-500/40', bg: 'bg-emerald-500/10', text: 'text-emerald-400', doneBg: 'bg-emerald-500/20' },
    },
  ]

  const doneCount    = steps.filter(s => s.done).length
  const allDone      = doneCount === steps.length
  const progressPct  = Math.round((doneCount / steps.length) * 100)

  if (dismissed && !allDone) return null
  if (loading) return (
    <div className="flex justify-center py-8"><Spinner color="primary" /></div>
  )

  return (
    <div className="rounded-3xl border overflow-hidden" style={{
      background: 'linear-gradient(135deg, rgba(139,92,246,0.06), rgba(6,182,212,0.04))',
      borderColor: allDone ? 'rgba(52,211,153,0.3)' : 'rgba(139,92,246,0.2)',
    }} dir="rtl">

      {/* Header */}
      <div className="px-6 py-5 flex items-center justify-between border-b border-white/5">
        <div className="flex items-center gap-3">
          <div style={{ width:40, height:40, borderRadius:12,
            background: allDone ? 'rgba(52,211,153,0.15)' : 'rgba(139,92,246,0.15)',
            display:'flex', alignItems:'center', justifyContent:'center' }}>
            {allDone
              ? <Icon paths="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" size={20} className="text-emerald-400" />
              : <Icon paths="M13 10V3L4 14h7v7l9-11h-7z" size={18} className="text-violet-400" />
            }
          </div>
          <div>
            <h3 className="font-bold text-foreground text-sm">
              {allDone ? '🎉 البوت جاهز تماماً!' : 'إعداد البوت — ابدأ في دقائق'}
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              {allDone
                ? 'أكملت كل خطوات الإعداد بنجاح'
                : `${doneCount} من ${steps.length} خطوات مكتملة`
              }
            </p>
          </div>
        </div>

        {/* Progress + dismiss */}
        <div className="flex items-center gap-3">
          {/* Progress ring */}
          <div className="relative w-10 h-10 flex-shrink-0">
            <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90">
              <circle cx="18" cy="18" r="15" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="3" />
              <circle cx="18" cy="18" r="15" fill="none"
                stroke={allDone ? '#34d399' : '#8b5cf6'} strokeWidth="3"
                strokeDasharray={`${progressPct * 0.942} 94.2`}
                strokeLinecap="round" style={{ transition: 'stroke-dasharray 0.5s ease' }} />
            </svg>
            <span className="absolute inset-0 flex items-center justify-center text-[10px] font-bold text-foreground">
              {progressPct}%
            </span>
          </div>

          {!allDone && (
            <button onClick={dismiss} className="text-slate-600 hover:text-slate-400 transition-colors p-1" title="إخفاء">
              <Icon paths="M6 18L18 6M6 6l12 12" size={14} />
            </button>
          )}
          {allDone && (
            <button onClick={dismiss} className="text-xs font-semibold text-emerald-500 hover:text-emerald-400 border border-emerald-500/30 rounded-lg px-3 py-1.5">
              تم، شكراً
            </button>
          )}
        </div>
      </div>

      {/* Steps */}
      <div className="p-5 grid grid-cols-1 sm:grid-cols-2 gap-3">
        {steps.map((step, idx) => (
          <div key={step.id}
            className={`relative flex items-start gap-3 rounded-2xl p-4 border transition-all duration-200 ${
              step.done
                ? `${step.color.doneBg} border-transparent`
                : 'bg-content1/40 border-white/5 hover:border-white/10'
            }`}
          >
            {/* Step number / check */}
            <div className={`w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 ring-1 ${step.color.ring} ${step.color.bg}`}>
              {step.done
                ? <Icon paths="M5 13l4 4L19 7" size={16} className="text-emerald-400" />
                : <span className={`text-sm font-black ${step.color.text}`}>{idx + 1}</span>
              }
            </div>

            <div className="flex-1 min-w-0">
              <p className={`text-sm font-bold mb-0.5 ${step.done ? 'line-through text-slate-500' : 'text-foreground'}`}>
                {step.title}
              </p>
              {!step.done && (
                <p className="text-xs text-slate-500 leading-relaxed mb-3">{step.desc}</p>
              )}
              {!step.done && (
                <Button size="sm" variant="flat"
                  className={`${step.color.bg} ${step.color.text} font-semibold text-xs h-8`}
                  isLoading={step.loading}
                  onPress={() => step.action()}>
                  {step.label}
                  {!step.loading && <Icon paths="M9 18l6-6-6-6" size={13} className="mr-1" />}
                </Button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
