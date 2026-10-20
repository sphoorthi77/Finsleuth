// @vitest-environment jsdom
import React from 'react';
import {describe,it,expect,vi,afterEach} from 'vitest';
import {render,screen,fireEvent,cleanup,waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {Landing,AuthPage,Shell,Auth} from './main';
import type {User} from './api';
afterEach(()=>{cleanup();vi.restoreAllMocks()});
describe('workspace interface',()=>{
 it('landing has separate demo, sign in and registration access',()=>{render(<MemoryRouter><Landing/></MemoryRouter>);expect(screen.getByRole('link',{name:'Explore the demo'}).getAttribute('href')).toBe('/demo');expect(screen.getByRole('link',{name:'Sign in'}).getAttribute('href')).toBe('/login');expect(screen.getByRole('link',{name:'Request access'}).getAttribute('href')).toBe('/register')});
 it('registration collects required identity and role fields',()=>{render(<MemoryRouter><AuthPage register/></MemoryRouter>);expect(screen.getByLabelText('Full name')).toBeTruthy();expect(screen.getByLabelText('Requested role')).toBeTruthy();expect(screen.getByLabelText('Password').getAttribute('minlength')).toBe('12')});
 it('authentication displays a useful backend error',async()=>{vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({detail:'Your account is pending'}),{status:403}));render(<MemoryRouter><AuthPage/></MemoryRouter>);fireEvent.change(screen.getByLabelText('Email address'),{target:{value:'test@example.test'}});fireEvent.change(screen.getByLabelText('Password'),{target:{value:'long-password'}});fireEvent.submit(screen.getByRole('button',{name:'Sign in'}).closest('form')!);await waitFor(()=>expect(screen.getByRole('alert').textContent).toContain('Your account is pending'))});
 it.each(['analyst','manager','admin'] as const)('renders only %s navigation',role=>{const user:User={id:'u',name:'Test',email:'test@example.test',role,scope:'operational',status:'active',organisation:'Test'};render(<MemoryRouter initialEntries={['/profile']}><Auth.Provider value={{user,setUser:()=>{}}}><Shell/></Auth.Provider></MemoryRouter>);expect(screen.queryByRole('link',{name:'Users & approvals'})).toBe(role==='admin'?screen.getByRole('link',{name:'Users & approvals'}):null);expect(screen.queryByRole('link',{name:'Review & assignments'})).toBe(role==='manager'?screen.getByRole('link',{name:'Review & assignments'}):null);expect(screen.queryByRole('link',{name:'Transaction alerts'})).toBe(role==='analyst'?screen.getByRole('link',{name:'Transaction alerts'}):null)});
});
