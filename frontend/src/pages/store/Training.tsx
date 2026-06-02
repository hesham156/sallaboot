import { useEffect, useRef, useState } from 'react'
import {
  Card, CardBody, CardHeader, Tabs, Tab,
  Button, Input, Textarea, Spinner, Chip, Switch, Divider,
} from '@heroui/react'
import { api, TrainingEntry } from '../../api'

interface Props { storeId: string }

function Icon({ paths, size = 14, className = '' }: { paths: string | string[]; size?: number; className?: string }) {
  const arr = Array.isArray(paths) ? paths : [paths]
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className={className}>
      {arr.map((d, i) => <path key={i} d={d} />)}
    </svg>
  )
}

const KIND_LABEL: Record<TrainingEntry['kind'], string> = {
  instruction: 'توجيه',
  faq:         'سؤال شائع',
  file:        'ملف مرجعي',
  lesson:      'درس مُتعلَّم',
}
const KIND_COLOR: Record<TrainingEntry['kind'], 'primary' | 'success' | 'warning' | 'secondary'> = {
  instruction: 'warning',
  faq:         'success',
  file:        'primary',
  lesson:      'secondary',
}
const KIND_ICON: Record<TrainingEntry['kind'], string> = {
  instruction: '🎯',
  faq:         '💬',
  file:        '📄',
  lesson:      '🧠',
}

export default function Training({ storeId }: Props) {
  const [items, setItems] = useState<TrainingEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState('')
  const [tab, setTab] = useState<string>('add-instruction')

  // Instruction / FAQ form
  const [title,   setTitle]   = useState('')
  const [content, setContent] = useState('')
  const [saving,  setSaving]  = useState(false)

  // File upload
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [fileTitle, setFileTitle] = useState('')
  const [uploading, setUploading] = useState(false)

  useEffect(() => { load() }, [storeId])

  async function load() {
    setLoading(true)
    try {
      const r = await api.listTraining(storeId)
      setItems(r.items)
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  async function addText(kind: 'instruction' | 'faq') {
    if (!title.trim() && !content.trim()) {
      setMsg('❌ اكتب عنوان أو محتوى أولاً'); return
    }
    setSaving(true); setMsg('')
    try {
      const r = await api.addTextTraining(storeId, { kind, title: title.trim(), content: content.trim() })
      setMsg(`✅ ${r.message}`)
      setTitle(''); setContent('')
      await load()
    } catch (e: unknown) {
      setMsg(`❌ ${e instanceof Error ? e.message : 'خطأ'}`)
    } finally { setSaving(false) }
  }

  async function uploadFile() {
    const f = fileInputRef.current?.files?.[0]
    if (!f) { setMsg('❌ اختر ملفاً أولاً'); return }
    setUploading(true); setMsg('')
    try {
      const r = await api.uploadTrainingFile(storeId, f, fileTitle.trim())
      let line = `✅ ${r.message} — ${r.filename}`
      if (r.size_chars > 0) line += ` (${r.size_chars.toLocaleString()} حرف)`
      if (r.warning) line += ` · ⚠️ ${r.warning}`
      setMsg(line)
      setFileTitle('')
      if (fileInputRef.current) fileInputRef.current.value = ''
      await load()
    } catch (e: unknown) {
      setMsg(`❌ ${e instanceof Error ? e.message : 'خطأ في الرفع'}`)
    } finally { setUploading(false) }
  }

  async function toggle(id: number, enabled: boolean) {
    try {
      await api.toggleTraining(storeId, id, enabled)
      setItems(prev => prev.map(it => it.id === id ? { ...it, enabled } : it))
    } catch (e) { console.error(e) }
  }

  async function remove(id: number) {
    if (!confirm('متأكد من حذف هذا التدريب؟')) return
    try {
      await api.deleteTraining(storeId, id)
      setItems(prev => prev.filter(it => it.id !== id))
    } catch (e) { console.error(e) }
  }

  // Field styles — taller, clearer, no built-in label (we render labels
  // explicitly above each field via <Field> to avoid HeroUI's outside-label
  // overlapping the placeholder in RTL).
  const inputCls = {
    inputWrapper: 'border-divider bg-content2 h-12 min-h-12 hover:border-slate-500 group-data-[focus=true]:border-primary',
    input:        'text-foreground text-sm placeholder:text-default-500',
  }
  const taCls = {
    inputWrapper: 'border-divider bg-content2 hover:border-slate-500 group-data-[focus=true]:border-primary py-2',
    input:        'text-foreground text-sm leading-relaxed placeholder:text-default-500',
  }

  const counts = {
    instruction: items.filter(i => i.kind === 'instruction').length,
    faq:         items.filter(i => i.kind === 'faq').length,
    file:        items.filter(i => i.kind === 'file').length,
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-5" dir="rtl">
      <header>
        <h1 className="text-xl font-bold text-foreground flex items-center gap-2">
          🎓 تدريب البوت
        </h1>
        <p className="text-sm text-default-500 mt-1">
          اكتب توجيهات للبوت، أو ضيف أسئلة شائعة وإجاباتها، أو ارفع ملفات مرجعية. البوت يستخدمها في كل رد.
        </p>
      </header>

      {msg && (
        <div className={`rounded-lg p-3 text-sm border ${
          msg.startsWith('✅')
            ? 'bg-success/10 border-success/20 text-success'
            : 'bg-danger/10 border-danger/20 text-danger'
        }`}>{msg}</div>
      )}

      {/* ════════════ ADD NEW ════════════ */}
      <Card className="bg-content1 border border-divider">
        <CardHeader className="px-5 py-4 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-purple-400" />
          <h2 className="font-bold text-sm">إضافة تدريب جديد</h2>
        </CardHeader>
        <Divider />
        <CardBody className="px-5 py-5">
          <Tabs
            selectedKey={tab}
            onSelectionChange={k => { setTab(String(k)); setTitle(''); setContent('') }}
            variant="bordered"
            classNames={{
              tabList: 'bg-content2 border border-divider p-1',
              cursor:  'bg-primary/15 border border-primary/30',
              tab:     'h-9 text-xs',
            }}
          >
            <Tab key="add-instruction" title="🎯 توجيه" />
            <Tab key="add-faq"         title="💬 سؤال + إجابة" />
            <Tab key="add-file"        title="📄 ملف مرجعي" />
          </Tabs>

          <div className="mt-5 space-y-5">
            {tab === 'add-instruction' && (
              <>
                <Field label="عنوان التوجيه" hint="اختياري">
                  <Input
                    placeholder="مثال: نبرة المحادثة"
                    value={title} onValueChange={setTitle}
                    variant="bordered" classNames={inputCls}
                  />
                </Field>
                <Field label="نص التوجيه">
                  <Textarea
                    placeholder="مثال: استخدم لغة عربية فصيحة وبسيطة. لا تخصم أكثر من ١٠٪. اعرض المنتجات بالأسعار قبل الضريبة."
                    value={content} onValueChange={setContent}
                    variant="bordered" minRows={4} maxRows={10}
                    classNames={taCls}
                  />
                </Field>
                <Button color="warning" isLoading={saving} onPress={() => addText('instruction')}
                        className="w-full font-bold h-11">
                  {saving ? '' : '🎯 إضافة التوجيه'}
                </Button>
              </>
            )}

            {tab === 'add-faq' && (
              <>
                <Field label="السؤال">
                  <Input
                    placeholder="مثال: كم مدة التسليم؟"
                    value={title} onValueChange={setTitle}
                    variant="bordered" classNames={inputCls}
                  />
                </Field>
                <Field label="الإجابة">
                  <Textarea
                    placeholder="مثال: مدة التسليم من ٣ إلى ٥ أيام عمل داخل الرياض، و٥ إلى ٧ أيام لباقي المدن. الشحن مجاني فوق ٢٠٠ ريال."
                    value={content} onValueChange={setContent}
                    variant="bordered" minRows={5} maxRows={12}
                    classNames={taCls}
                  />
                </Field>
                <Button color="success" isLoading={saving} onPress={() => addText('faq')}
                        className="w-full font-bold h-11">
                  {saving ? '' : '💬 إضافة السؤال والإجابة'}
                </Button>
              </>
            )}

            {tab === 'add-file' && (
              <>
                <div className="bg-blue-500/5 border border-blue-500/20 rounded-xl p-4 text-xs text-blue-300 leading-relaxed">
                  <p className="font-bold mb-1">📋 الأنواع المدعومة:</p>
                  <p>PDF · TXT · MD · CSV · LOG (حتى 20 MB لكل ملف)</p>
                  <p className="mt-2 opacity-80">
                    💡 ارفع كتالوجات المنتجات، دليل الخدمات، شروط الاستخدام، أي مستند تحب البوت يقرأه ويستفيد منه.
                  </p>
                </div>

                <Field label="عنوان المرجع" hint="اختياري">
                  <Input
                    placeholder="مثال: كتالوج صيف 2025"
                    value={fileTitle} onValueChange={setFileTitle}
                    variant="bordered" classNames={inputCls}
                  />
                </Field>

                <Field label="الملف">
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf,.txt,.md,.csv,.log"
                    className="block w-full text-xs text-default-300 rounded-xl border border-divider bg-content2 p-2.5 file:ml-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-primary/15 file:text-primary file:cursor-pointer file:font-semibold hover:file:bg-primary/25 cursor-pointer"
                  />
                </Field>

                <Button color="primary" isLoading={uploading} onPress={uploadFile}
                        className="w-full font-bold h-11 bg-gradient-to-r from-blue-600 to-indigo-600 shadow-lg shadow-blue-500/20">
                  {uploading ? '' : '📤 رفع وقراءة الملف'}
                </Button>
              </>
            )}
          </div>
        </CardBody>
      </Card>

      {/* ════════════ LIST ════════════ */}
      <Card className="bg-content1 border border-divider">
        <CardHeader className="px-5 py-4 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-400" />
            <h2 className="font-bold text-sm">المواد التدريبية الحالية</h2>
          </div>
          <div className="flex gap-1.5">
            <Chip size="sm" variant="flat" color="warning">🎯 {counts.instruction}</Chip>
            <Chip size="sm" variant="flat" color="success">💬 {counts.faq}</Chip>
            <Chip size="sm" variant="flat" color="primary">📄 {counts.file}</Chip>
          </div>
        </CardHeader>
        <Divider />
        <CardBody className="px-3 py-3">
          {loading ? (
            <div className="flex items-center justify-center py-12"><Spinner color="primary" /></div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center gap-2">
              <span className="text-4xl">🎓</span>
              <p className="text-sm text-default-400 font-semibold">لم يبدأ التدريب بعد</p>
              <p className="text-xs text-default-500">
                اضف أول توجيه أو سؤال شائع لتعليم البوت
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {items.map(it => (
                <div
                  key={it.id}
                  className={`rounded-xl border p-3 transition-colors ${
                    it.enabled
                      ? 'bg-content2 border-divider'
                      : 'bg-content2/40 border-divider opacity-60'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <span className="text-xl flex-shrink-0">{KIND_ICON[it.kind]}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1 flex-wrap">
                        <Chip size="sm" variant="flat" color={KIND_COLOR[it.kind]}>
                          {KIND_LABEL[it.kind]}
                        </Chip>
                        {it.size_chars > 0 && (
                          <span className="text-[10px] text-default-500">
                            {it.size_chars.toLocaleString()} حرف
                          </span>
                        )}
                        <span className="text-[10px] text-default-500 mr-auto">
                          {new Date(it.created_at).toLocaleDateString('ar-SA')}
                        </span>
                      </div>
                      {it.title && (
                        <p className="text-sm font-bold text-foreground truncate">{it.title}</p>
                      )}
                      {it.content && (
                        <p className="text-xs text-default-400 leading-relaxed mt-1 line-clamp-3 whitespace-pre-wrap">
                          {it.content.length > 240 ? it.content.slice(0, 240) + '…' : it.content}
                        </p>
                      )}
                      {it.kind === 'file' && it.file_id && (
                        <a
                          href={`/file/${it.file_id}`} target="_blank" rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-[11px] text-blue-400 hover:text-blue-300 mt-2"
                        >
                          <Icon paths="M21 15a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v7z" size={11} />
                          {it.file_name || 'تحميل الملف'}
                        </a>
                      )}
                    </div>
                    <div className="flex flex-col items-end gap-2 flex-shrink-0">
                      <Switch
                        size="sm"
                        isSelected={it.enabled}
                        onValueChange={v => toggle(it.id, v)}
                      />
                      <button
                        onClick={() => remove(it.id)}
                        className="text-default-400 hover:text-danger transition-colors"
                        aria-label="حذف"
                      >
                        <Icon paths={[
                          'M19 7L18.1 19.2A2 2 0 0116.1 21H7.9A2 2 0 015.9 19.2L5 7',
                          'M10 11v6', 'M14 11v6', 'M3 7h18',
                          'M8 7V4a1 1 0 011-1h6a1 1 0 011 1v3',
                        ]} size={14} />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  )
}

// ── Field: explicit label above the control (reliable in RTL) ───────────────
function Field({ label, hint, children }: {
  label: string; hint?: string; children: React.ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <label className="flex items-center gap-1.5 text-xs font-semibold text-default-500 px-0.5">
        {label}
        {hint && <span className="text-[10px] font-normal text-default-400">({hint})</span>}
      </label>
      {children}
    </div>
  )
}
