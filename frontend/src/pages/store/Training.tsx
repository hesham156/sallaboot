import { useEffect, useRef, useState } from 'react'
import { Button, Input, Textarea, Spinner, Switch } from '@heroui/react'
import { api, TrainingEntry } from '../../api'
import { PageHeader } from '../../components/ui'

interface Props { storeId: string }

function Icon({ d, size = 14, className = '' }: { d: string | string[]; size?: number; className?: string }) {
  const paths = Array.isArray(d) ? d : [d]
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
      className={className}>
      {paths.map((p, i) => <path key={i} d={p} />)}
    </svg>
  )
}

function Msg({ text }: { text: string }) {
  if (!text) return null
  const ok = text.startsWith('✅')
  return (
    <div className={`rounded-xl px-3 py-2.5 text-xs border flex items-start gap-2 leading-relaxed ${
      ok ? 'bg-success/8 border-success/20 text-success' : 'bg-danger/8 border-danger/20 text-danger'
    }`}>
      <span className="flex-shrink-0 mt-0.5">{ok ? '✓' : '!'}</span>
      <span>{text}</span>
    </div>
  )
}

const KIND_META = {
  instruction: { emoji: '🎯', label: 'توجيه',       color: 'text-amber-400  bg-amber-500/10  border-amber-500/20'  },
  faq:         { emoji: '💬', label: 'سؤال شائع',   color: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' },
  file:        { emoji: '📄', label: 'ملف مرجعي',  color: 'text-blue-400   bg-blue-500/10   border-blue-500/20'   },
  lesson:      { emoji: '🧠', label: 'درس مُتعلَّم', color: 'text-violet-400  bg-violet-500/10  border-violet-500/20'  },
} as const

type AddTab = 'instruction' | 'faq' | 'file'

export default function Training({ storeId }: Props) {
  const [items,    setItems]    = useState<TrainingEntry[]>([])
  const [loading,  setLoading]  = useState(true)
  const [msg,      setMsg]      = useState('')
  const [addTab,   setAddTab]   = useState<AddTab>('instruction')

  // Text form
  const [title,   setTitle]   = useState('')
  const [content, setContent] = useState('')
  const [saving,  setSaving]  = useState(false)

  // File upload
  const fileRef  = useRef<HTMLInputElement>(null)
  const [fileTitle, setFileTitle] = useState('')
  const [uploading, setUploading] = useState(false)
  const [dragOver,  setDragOver]  = useState(false)
  const [fileName,  setFileName]  = useState('')

  useEffect(() => { load() }, [storeId])

  async function load() {
    setLoading(true)
    try { const r = await api.listTraining(storeId); setItems(r.items) }
    catch { /* ignore */ } finally { setLoading(false) }
  }

  async function addText() {
    if (!title.trim() && !content.trim()) { setMsg('❌ اكتب عنوان أو محتوى أولاً'); return }
    setSaving(true); setMsg('')
    try {
      const r = await api.addTextTraining(storeId, {
        kind: addTab as 'instruction' | 'faq',
        title: title.trim(), content: content.trim(),
      })
      setMsg(`✅ ${r.message}`)
      setTitle(''); setContent(''); await load()
    } catch (e: unknown) { setMsg(`❌ ${e instanceof Error ? e.message : 'خطأ'}`) }
    finally { setSaving(false) }
  }

  async function uploadFile() {
    const f = fileRef.current?.files?.[0]
    if (!f) { setMsg('❌ اختر ملفاً أولاً'); return }
    setUploading(true); setMsg('')
    try {
      const r = await api.uploadTrainingFile(storeId, f, fileTitle.trim())
      let line = `✅ ${r.message}`
      if (r.size_chars > 0) line += ` — ${r.size_chars.toLocaleString()} حرف`
      if (r.warning) line += ` · ⚠️ ${r.warning}`
      setMsg(line)
      setFileTitle(''); setFileName('')
      if (fileRef.current) fileRef.current.value = ''
      await load()
    } catch (e: unknown) { setMsg(`❌ ${e instanceof Error ? e.message : 'خطأ في الرفع'}`) }
    finally { setUploading(false) }
  }

  async function toggle(id: number, enabled: boolean) {
    try {
      await api.toggleTraining(storeId, id, enabled)
      setItems(p => p.map(it => it.id === id ? { ...it, enabled } : it))
    } catch { /* ignore */ }
  }

  async function remove(id: number) {
    if (!confirm('متأكد من حذف هذا التدريب؟')) return
    try { await api.deleteTraining(storeId, id); setItems(p => p.filter(it => it.id !== id)) }
    catch { /* ignore */ }
  }

  const counts = {
    instruction: items.filter(i => i.kind === 'instruction').length,
    faq:         items.filter(i => i.kind === 'faq').length,
    file:        items.filter(i => i.kind === 'file').length,
    lesson:      items.filter(i => i.kind === 'lesson').length,
  }

  const ADD_TABS: { key: AddTab; emoji: string; label: string }[] = [
    { key: 'instruction', emoji: '🎯', label: 'توجيه'       },
    { key: 'faq',         emoji: '💬', label: 'سؤال + إجابة' },
    { key: 'file',        emoji: '📄', label: 'ملف'          },
  ]

  const inputCls = {
    inputWrapper: 'border-divider bg-content2 h-10 min-h-10 hover:border-default-400 group-data-[focus=true]:!border-primary rounded-xl',
    input: 'text-sm text-foreground placeholder:text-default-400',
  }
  const taCls = {
    inputWrapper: 'border-divider bg-content2 hover:border-default-400 group-data-[focus=true]:!border-primary rounded-xl py-2',
    input: 'text-sm text-foreground placeholder:text-default-400 leading-relaxed',
  }

  /* ── RENDER ── */
  return (
    <div className="h-full flex flex-col" dir="rtl">

      {/* ── Header ── */}
      <div className="px-6 pt-6 pb-4 flex items-center justify-between flex-wrap gap-3">
        <PageHeader
          title="تدريب البوت"
          subtitle="علّم البوت توجيهات، أسئلة شائعة، وملفات مرجعية"
          icon="M12 14l9-5-9-5-9 5 9 5zm0 0l6.16-3.42A12 12 0 0112 21a12 12 0 01-6.16-10.42L12 14z"
        />
        {/* Counters */}
        <div className="flex gap-2 text-xs">
          {Object.entries(counts).filter(([,v]) => v > 0).map(([k, v]) => {
            const m = KIND_META[k as keyof typeof KIND_META]
            return (
              <span key={k} className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border font-semibold ${m.color}`}>
                {m.emoji} {v}
              </span>
            )
          })}
        </div>
      </div>

      {/* ── Main split layout ── */}
      <div className="flex-1 overflow-hidden flex gap-0 px-6 pb-6">

        {/* ══ LEFT: Add form ══ */}
        <div className="w-80 flex-shrink-0 flex flex-col gap-3 overflow-y-auto pl-4">

          {/* Tab pills */}
          <div className="flex gap-1.5 bg-content2 rounded-xl p-1 border border-divider flex-shrink-0">
            {ADD_TABS.map(t => (
              <button key={t.key}
                onClick={() => { setAddTab(t.key); setTitle(''); setContent(''); setMsg('') }}
                className={`flex-1 flex items-center justify-center gap-1 py-2 text-xs font-bold rounded-lg transition-all ${
                  addTab === t.key
                    ? 'bg-content1 text-foreground shadow-sm border border-divider'
                    : 'text-default-400 hover:text-foreground'
                }`}>
                <span>{t.emoji}</span>
                <span className="hidden sm:inline">{t.label}</span>
              </button>
            ))}
          </div>

          {/* ── Instruction ── */}
          {addTab === 'instruction' && (
            <div className="space-y-3">
              <div className="bg-amber-500/6 border border-amber-500/20 rounded-xl px-3 py-2.5 text-xs text-amber-300 leading-relaxed">
                <p className="font-bold mb-1">🎯 ما هو التوجيه؟</p>
                تعليمات صريحة للبوت: أسلوب الرد، سياسات المتجر، ما يجوز وما لا يجوز.
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-bold text-default-400 block">العنوان (اختياري)</label>
                <Input variant="bordered" classNames={inputCls}
                  placeholder="مثال: نبرة المحادثة"
                  value={title} onValueChange={setTitle} />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-bold text-default-400 block">نص التوجيه</label>
                <Textarea variant="bordered" classNames={taCls} minRows={5} maxRows={10}
                  placeholder="مثال: استخدم لغة عربية بسيطة. لا تخصم أكثر من ١٠٪. اعرض الأسعار قبل الضريبة."
                  value={content} onValueChange={setContent} />
              </div>
              <Msg text={msg} />
              <Button color="warning" isLoading={saving} onPress={addText}
                className="w-full font-bold h-10">
                {saving ? '' : '🎯 إضافة التوجيه'}
              </Button>
            </div>
          )}

          {/* ── FAQ ── */}
          {addTab === 'faq' && (
            <div className="space-y-3">
              <div className="bg-emerald-500/6 border border-emerald-500/20 rounded-xl px-3 py-2.5 text-xs text-emerald-300 leading-relaxed">
                <p className="font-bold mb-1">💬 ما هو الـ FAQ؟</p>
                سؤال وجوابه الكامل — البوت يستخدم نفس صياغتك عند مواجهة سؤال مشابه.
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-bold text-default-400 block">السؤال</label>
                <Input variant="bordered" classNames={inputCls}
                  placeholder="مثال: كم مدة التسليم؟"
                  value={title} onValueChange={setTitle} />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-bold text-default-400 block">الإجابة الكاملة</label>
                <Textarea variant="bordered" classNames={taCls} minRows={5} maxRows={10}
                  placeholder="مثال: التسليم من ٣ إلى ٥ أيام داخل الرياض، وحتى ٧ أيام لباقي المدن."
                  value={content} onValueChange={setContent} />
              </div>
              <Msg text={msg} />
              <Button color="success" isLoading={saving} onPress={addText}
                className="w-full font-bold h-10">
                {saving ? '' : '💬 إضافة السؤال والإجابة'}
              </Button>
            </div>
          )}

          {/* ── File ── */}
          {addTab === 'file' && (
            <div className="space-y-3">
              <div className="bg-blue-500/6 border border-blue-500/20 rounded-xl px-3 py-2.5 text-xs text-blue-300 leading-relaxed">
                <p className="font-bold mb-1">📋 الأنواع المقبولة</p>
                <p>PDF · TXT · MD · CSV (حتى 20 MB)</p>
                <p className="mt-1 opacity-75">كتالوجات، شروط، أدلة — أي مستند يفيد البوت.</p>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-bold text-default-400 block">عنوان المرجع (اختياري)</label>
                <Input variant="bordered" classNames={inputCls}
                  placeholder="مثال: كتالوج صيف 2025"
                  value={fileTitle} onValueChange={setFileTitle} />
              </div>

              {/* Drop zone */}
              <div
                onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={e => {
                  e.preventDefault(); setDragOver(false)
                  const f = e.dataTransfer.files[0]
                  if (f && fileRef.current) {
                    const dt = new DataTransfer(); dt.items.add(f)
                    fileRef.current.files = dt.files
                    setFileName(f.name)
                  }
                }}
                onClick={() => fileRef.current?.click()}
                className={`relative border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all ${
                  dragOver
                    ? 'border-primary bg-primary/8 scale-[1.01]'
                    : fileName
                    ? 'border-success/50 bg-success/5'
                    : 'border-divider bg-content2 hover:border-default-400'
                }`}>
                <input ref={fileRef} type="file" accept=".pdf,.txt,.md,.csv,.log"
                  className="hidden"
                  onChange={e => setFileName(e.target.files?.[0]?.name || '')} />
                {fileName ? (
                  <div className="space-y-1">
                    <p className="text-lg">📄</p>
                    <p className="text-xs font-bold text-success truncate">{fileName}</p>
                    <p className="text-[10px] text-default-500">اضغط لتغيير الملف</p>
                  </div>
                ) : (
                  <div className="space-y-1">
                    <p className="text-2xl">📂</p>
                    <p className="text-xs font-bold text-foreground">اسحب الملف هنا أو اضغط للاختيار</p>
                    <p className="text-[10px] text-default-400">PDF, TXT, MD, CSV</p>
                  </div>
                )}
              </div>

              <Msg text={msg} />
              <Button color="primary" isLoading={uploading} onPress={uploadFile}
                className="w-full font-bold h-10 bg-gradient-to-r from-blue-600 to-indigo-600">
                {uploading ? '' : '📤 رفع وقراءة الملف'}
              </Button>
            </div>
          )}
        </div>

        {/* Divider */}
        <div className="w-px bg-divider flex-shrink-0 mx-1" />

        {/* ══ RIGHT: Training list ══ */}
        <div className="flex-1 overflow-y-auto pr-4 pl-1">

          {loading ? (
            <div className="flex justify-center py-16"><Spinner color="primary" /></div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center gap-3 pb-8">
              <span className="text-5xl opacity-40">🎓</span>
              <p className="text-sm font-bold text-default-400">لا توجد مواد تدريبية بعد</p>
              <p className="text-xs text-default-500">أضف أول توجيه أو سؤال شائع من اليسار</p>
            </div>
          ) : (
            <div className="space-y-2">
              {items.map(it => {
                const m = KIND_META[it.kind] || KIND_META.instruction
                return (
                  <div key={it.id}
                    className={`group rounded-xl border p-3 transition-all ${
                      it.enabled
                        ? 'bg-content2/60 border-divider hover:border-default-400'
                        : 'bg-content2/30 border-divider/50 opacity-50'
                    }`}>
                    <div className="flex items-start gap-2.5">

                      {/* Kind badge */}
                      <span className={`text-[10px] font-bold px-2 py-1 rounded-lg border flex-shrink-0 mt-0.5 ${m.color}`}>
                        {m.emoji} {m.label}
                      </span>

                      <div className="flex-1 min-w-0">
                        {it.title && (
                          <p className="text-sm font-bold text-foreground truncate">{it.title}</p>
                        )}
                        {it.content && (
                          <p className="text-xs text-default-400 leading-relaxed mt-0.5 line-clamp-2">
                            {it.content.length > 180 ? it.content.slice(0, 180) + '…' : it.content}
                          </p>
                        )}
                        <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                          {it.kind === 'file' && it.file_id && (
                            <a href={`/file/${it.file_id}`} target="_blank" rel="noopener noreferrer"
                              className="text-[10px] text-blue-400 hover:text-blue-300 flex items-center gap-0.5">
                              <Icon d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z M14 2v6h6 M16 13H8 M16 17H8 M10 9H8" size={10} />
                              {it.file_name || 'تحميل'}
                            </a>
                          )}
                          {it.size_chars > 0 && (
                            <span className="text-[10px] text-default-500">{it.size_chars.toLocaleString()} حرف</span>
                          )}
                          <span className="text-[10px] text-default-600 mr-auto">
                            {new Date(it.created_at).toLocaleDateString('ar-SA')}
                          </span>
                        </div>
                      </div>

                      {/* Actions */}
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <Switch size="sm" isSelected={it.enabled}
                          onValueChange={v => toggle(it.id, v)} />
                        <button onClick={() => remove(it.id)}
                          className="w-7 h-7 flex items-center justify-center rounded-lg text-default-400 hover:text-danger hover:bg-danger/10 transition-colors opacity-0 group-hover:opacity-100">
                          <Icon d={['M19 7L18.1 19.2A2 2 0 0116.1 21H7.9A2 2 0 015.9 19.2L5 7','M3 7h18','M8 7V4a1 1 0 011-1h6a1 1 0 011 1v3']} size={13} />
                        </button>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
