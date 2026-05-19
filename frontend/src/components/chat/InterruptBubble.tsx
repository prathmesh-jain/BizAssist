import React from 'react';
import { motion } from 'framer-motion';
import { Check, X, AlertCircle, Upload, Send } from 'lucide-react';
import type { Interrupt } from '../../types';
import useChatStore from '../../store/chatStore';

interface InterruptBubbleProps {
    chatId: string;
    interrupt: Interrupt;
}

const InterruptBubble: React.FC<InterruptBubbleProps> = ({ chatId, interrupt }) => {
    const resolveInterrupt = useChatStore(state => state.resolveInterrupt);
    const resolveInterruptWithFiles = useChatStore(state => state.resolveInterruptWithFiles);
    const isLoading = useChatStore(state => state.isLoading);
    const [textValue, setTextValue] = React.useState('');
    const [fileName, setFileName] = React.useState('');

    const handleAction = async (action: 'accept' | 'reject') => {
        await resolveInterrupt(chatId, action, interrupt.data);
    };

    const handleTextSubmit = async () => {
        const value = textValue.trim();
        if (!value) return;
        await resolveInterrupt(chatId, 'accept', value);
    };

    const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) return;
        setFileName(file.name);
        await resolveInterruptWithFiles(chatId, [file]);
    };

    const interruptType = interrupt.interrupt_type || 'accept_decline';
    const helperText = {
        accept_decline: 'The AI agent needs your approval to proceed with this action.',
        yes_no_confirmation: 'Please confirm how you want the agent to proceed.',
        text_input: 'Please provide the missing detail so the agent can continue.',
        file_upload: 'Please upload the file needed for this task.',
    }[interruptType];

    return (
        <motion.div
            initial={{ opacity: 0, y: 10, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            className="my-4 mx-auto max-w-lg overflow-hidden rounded-2xl border border-white/20 bg-white/10 p-6 shadow-2xl backdrop-blur-md dark:bg-slate-900/40"
        >
            <div className="flex items-start gap-4">
                <div className="flex-shrink-0 rounded-full bg-blue-500/20 p-2 text-blue-500">
                    <AlertCircle size={24} />
                </div>
                <div className="flex-1">
                    <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-100">
                        {interrupt.question || 'Confirmation Required'}
                    </h3>
                    <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
                        {helperText}
                    </p>

                    {interrupt.data && (
                        <div className="mt-4 rounded-lg bg-slate-100/50 p-3 text-xs font-mono text-slate-700 dark:bg-slate-800/50 dark:text-slate-300">
                            <pre className="whitespace-pre-wrap">
                                {JSON.stringify(interrupt.data, null, 2)}
                            </pre>
                        </div>
                    )}

                    {interruptType === 'text_input' && (
                        <div className="mt-6 flex items-center gap-2">
                            <input
                                value={textValue}
                                onChange={(event) => setTextValue(event.target.value)}
                                onKeyDown={(event) => {
                                    if (event.key === 'Enter') handleTextSubmit();
                                }}
                                disabled={isLoading}
                                className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 outline-none transition focus:border-blue-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                                placeholder="Type your answer"
                            />
                            <button
                                onClick={handleTextSubmit}
                                disabled={isLoading || !textValue.trim()}
                                className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 text-white transition hover:bg-blue-700 disabled:opacity-50"
                                title="Submit"
                            >
                                <Send size={18} />
                            </button>
                        </div>
                    )}

                    {interruptType === 'file_upload' && (
                        <label className="mt-6 flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center transition hover:border-blue-500 hover:bg-blue-50 dark:border-slate-700 dark:bg-slate-800/60 dark:hover:bg-slate-800">
                            <Upload className="mb-2 h-6 w-6 text-blue-500" />
                            <span className="text-sm font-medium text-slate-800 dark:text-slate-100">
                                {fileName || 'Choose a file'}
                            </span>
                            <input
                                type="file"
                                className="hidden"
                                disabled={isLoading}
                                onChange={handleFileChange}
                            />
                        </label>
                    )}

                    {(interruptType === 'accept_decline' || interruptType === 'yes_no_confirmation') && (
                        <div className="mt-6 flex items-center gap-3">
                            <button
                                onClick={() => handleAction('accept')}
                                disabled={isLoading}
                                className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white shadow-lg transition-all hover:bg-blue-700 hover:shadow-blue-500/25 active:scale-95 disabled:opacity-50"
                            >
                                <Check size={18} />
                                {interruptType === 'yes_no_confirmation' ? 'Yes' : 'Accept'}
                            </button>
                            <button
                                onClick={() => handleAction('reject')}
                                disabled={isLoading}
                                className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition-all hover:bg-slate-50 active:scale-95 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
                            >
                                <X size={18} />
                                {interruptType === 'yes_no_confirmation' ? 'No' : 'Reject'}
                            </button>
                        </div>
                    )}
                </div>
            </div>
        </motion.div>
    );
};

export default InterruptBubble;
