import { useCallback, useState } from 'react';

/**
 * useFormModal — état de modal + formulaire.
 *
 * Exemple :
 *   const modal = useFormModal({ name: '' });
 *   <button onClick={() => modal.open({ name: 'preset' })}>Edit</button>
 *   {modal.isOpen && <Modal onClose={modal.close}>
 *     <input value={modal.values.name} onChange={e => modal.set('name', e.target.value)} />
 *   </Modal>}
 */
export function useFormModal(initial = {}) {
  const [isOpen, setIsOpen] = useState(false);
  const [values, setValues] = useState(initial);

  const open = useCallback((preset) => {
    setValues(preset ?? initial);
    setIsOpen(true);
  }, [initial]);

  const close = useCallback(() => {
    setIsOpen(false);
  }, []);

  const set = useCallback((key, value) => {
    setValues(v => ({ ...v, [key]: value }));
  }, []);

  const reset = useCallback(() => {
    setValues(initial);
  }, [initial]);

  return { isOpen, values, open, close, set, reset, setValues };
}

export default useFormModal;
