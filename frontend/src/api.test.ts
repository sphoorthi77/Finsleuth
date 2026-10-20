import {describe,it,expect,vi,afterEach} from 'vitest';
import {api,post,money} from './api';
afterEach(()=>vi.restoreAllMocks());
describe('typed API client',()=>{
 it('sends cookies and mutation verification header',async()=>{const fetcher=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({id:'case-1'}),{status:200}));expect(await post('/cases',{title:'Test'})).toEqual({id:'case-1'});const options=fetcher.mock.calls[0][1]!;expect(options.credentials).toBe('include');expect((options.headers as Record<string,string>)['X-Finsleuth']).toBe('1');expect(options.method).toBe('POST')});
 it('preserves useful backend errors',async()=>{vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({detail:'Account is pending'}),{status:403}));await expect(api('/auth/me')).rejects.toThrow('Account is pending')});
 it('formats monetary values in INR',()=>expect(money(2500)).toContain('2,500'));
});
