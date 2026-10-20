import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./e2e',use:{baseURL:'http://127.0.0.1:5173',headless:true,screenshot:'only-on-failure'},timeout:120000,expect:{timeout:30000},workers:1,reporter:'list'});
