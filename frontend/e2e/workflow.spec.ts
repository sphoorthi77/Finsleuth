import {test,expect} from '@playwright/test';
test('analyst investigation → manager review → administrator governance',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/');await expect(page.getByRole('heading',{name:/See the bigger/})).toBeVisible();
 await page.screenshot({path:'test-results/landing-qa.png',fullPage:true});
 await page.getByRole('link',{name:'Explore the demo',exact:true}).click();
 await page.locator('.persona').filter({has:page.getByRole('heading',{name:'Bank Analyst',exact:true})}).getByRole('button').click();
 await expect(page.getByRole('heading',{name:'Fraud detection dashboard'})).toBeVisible();
 await expect(page.locator('tbody tr').first()).toBeVisible();
 await page.screenshot({path:'test-results/dashboard-qa.png',fullPage:true});
 await page.locator('tbody tr').first().getByRole('link').first().click();
 await page.getByRole('button',{name:'Score & explain'}).click();
 await expect(page.locator('.contribution')).toHaveCount(8);
 await page.getByRole('button',{name:'Create investigation'}).click();
 await page.getByLabel('Case title').fill('Browser verification case');
 await page.getByLabel('Reason for investigation').fill('Check recorded activity and model explanation before review.');
 await page.getByRole('button',{name:'Save draft'}).click();
 await expect(page.getByRole('heading',{name:'Browser verification case'})).toBeVisible();
 await page.getByLabel('Add an observation').fill('Observed model signals and source transaction. No conclusion of fraud.');
 await page.getByRole('button',{name:'Save note'}).click();
 await expect(page.getByText('Observed model signals and source transaction. No conclusion of fraud.')).toBeVisible();
 await page.getByRole('button',{name:'Submit for review'}).click();
 await expect(page.getByRole('button',{name:'Submit for review'})).toHaveCount(0);
 await page.getByRole('link',{name:'Switch demo persona'}).click();
 await page.locator('.persona').filter({has:page.getByRole('heading',{name:'Compliance Manager',exact:true})}).getByRole('button').click();
 await expect(page.getByRole('heading',{name:'Compliance command centre'})).toBeVisible();
 await page.getByRole('link',{name:'Review & assignments',exact:true}).click();
 await page.getByRole('link',{name:'Browser verification case'}).click();
 await page.getByLabel('Review decision').selectOption('closed');
 await page.getByLabel('Decision rationale').fill('Reviewed recorded evidence; no further action in this dataset test case.');
 await page.getByRole('button',{name:'Record decision'}).click();
 await expect(page.getByText('Reviewed recorded evidence; no further action in this dataset test case.')).toBeVisible();
 await page.getByRole('link',{name:'Switch demo persona'}).click();
 await page.locator('.persona').filter({has:page.getByRole('heading',{name:'System Administrator',exact:true})}).getByRole('button').click();
 await expect(page.getByRole('heading',{name:'Administration overview'})).toBeVisible();
 await page.getByRole('link',{name:'Models & deployment'}).click();
 await expect(page.locator('tbody tr')).toHaveCount(5);
 await page.getByRole('button',{name:'Report',exact:true}).first().click();
 await expect(page.getByRole('heading',{name:'Confusion matrix'})).toBeVisible();
 await page.getByRole('button',{name:'Close',exact:true}).click();
 await page.getByRole('button',{name:'Report',exact:true}).last().click();
 await expect(page.getByRole('heading',{name:'Confusion matrix'})).toBeVisible();
 expect(errors).toEqual([]);
});
test('responsive entry and recorded graph',async({page})=>{
 await page.setViewportSize({width:390,height:844});await page.goto('/');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
 await page.goto('/demo');await page.locator('.persona').first().getByRole('button').click();
 await page.getByRole('button',{name:'Toggle navigation'}).click();
 await page.getByRole('link',{name:'Network analysis',exact:true}).click();
 await expect(page.locator('.network-canvas canvas').first()).toBeVisible();
 await page.screenshot({path:'test-results/mobile-qa.png',fullPage:true});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test('home logo, demo exits and every role navigation page',async({page})=>{
 test.setTimeout(240000);
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 for(const role of ['Bank Analyst','Compliance Manager','System Administrator']){
  await page.goto('/demo');await page.getByRole('link',{name:'Back to home',exact:true}).click();await expect(page).toHaveURL('/');
  await page.goto('/demo');await page.locator('.persona').filter({has:page.getByRole('heading',{name:role,exact:true})}).getByRole('button').click();
  await expect(page.locator('.dash-kpis')).toBeVisible();
  await page.getByRole('link',{name:'Finsleuth home',exact:true}).click();await expect(page).toHaveURL('/');
  await page.goto('/app');await expect(page.locator('.dash-kpis')).toBeVisible();
  const links=await page.locator('.sidebar nav a').evaluateAll(elements=>elements.map(el=>el.getAttribute('href')!));
  for(const link of links){await page.goto(link);await expect(page.locator('.page')).toBeVisible();await expect(page.locator('.page')).not.toContainText('Your role cannot perform this action');}
  await page.goto('/app');await page.getByRole('button',{name:'Exit demo',exact:true}).click();await expect(page).toHaveURL('/');
  await page.goto('/app');await expect(page).toHaveURL('/login');
 }
 expect(errors).toEqual([]);
});

test('registration returns to a usable sign-in form and correct logo',async({page})=>{
 await page.goto('/register');
 await expect(page.locator('.brand-logo')).toHaveAttribute('src','/finsleuth-logo.png');
 await expect(page.getByLabel('Requested role').locator('option')).toHaveCount(2);
 await page.getByLabel('Full name').fill('Browser Applicant');
 await page.getByLabel('Email address').fill(`browser-${Date.now()}@example.test`);
 await page.getByLabel('Organisation').fill('Test Bank');
 await page.getByLabel('Password',{exact:true}).fill('browser-test-password');
 await page.getByLabel('Reason for access').fill('Investigate transactions for the bank');
 await page.getByRole('button',{name:'Submit registration'}).click();
 await expect(page.getByRole('heading',{name:'Request submitted'})).toBeVisible();
 await page.getByRole('link',{name:'Return to sign in'}).click();
 await expect(page.getByRole('button',{name:'Sign in',exact:true})).toBeVisible();
 await expect(page.getByLabel('Email address')).toBeVisible();
 await page.screenshot({path:'test-results/sign-in-qa.png',fullPage:true});
});


test('manager cannot enter model administration and audit is readable',async({page})=>{
 await page.goto('/demo');await page.locator('.persona').filter({has:page.getByRole('heading',{name:'Compliance Manager',exact:true})}).getByRole('button').click();
 await expect(page.getByRole('link',{name:'Model performance',exact:true})).toHaveCount(0);
 await page.goto('/app/models');await expect(page.getByRole('heading',{name:'Access restricted'})).toBeVisible();
 await page.goto('/app/audit');await expect(page.locator('.audit-item').first()).toBeVisible();
 await page.locator('.audit-item summary').first().click();await expect(page.locator('.audit-item pre')).toHaveCount(0);
 await expect(page.getByRole('link',{name:'Open affected case'}).first()).toBeVisible();
 await page.screenshot({path:'test-results/audit-qa.png',fullPage:true});
});
