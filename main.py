import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import aiohttp
import asyncio
import re
from database import Database

# Load environment variables
load_dotenv()

# Initialize database
db = Database()

# Bot configuration
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Store pending order (in production, use a database)
pending_order = {}

# Store active orders (in production, use a database)
active_orders = {}

# Store overdose reports (in production, use a database)
overdose_reports = {}

# Store API key (in production, use a database)
stored_api_key = None

# Dynamic pricing configuration (in production, use a database)
pricing_config = {
    'xan': {
        # Admin-configured XAN pricing will be added here via /setxanprice
        # Example: 12: {'cost': 1, 'reward': 4}
    },
    'extc': {
        # Admin-configured EXTC pricing will be added here via /setextcprice  
        # Example: 1: {'cost': 3, 'edvds': 3, 'xanax': 4, 'ecstasy': 1}
    }
}

# Auto check settings
auto_check_enabled = False
auto_check_interval = 5  # Default 5 minutes
last_check_time = datetime.now()
processed_events = set()  # Track processed events to avoid duplicates

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

@bot.tree.command(name="viewcoverage", description="View coverage records from the database")
@app_commands.describe(
    status="Filter by status (pending, active, etc)",
    user="Filter by specific user",
    limit="Number of records to show (max 20)"
)
async def view_coverage(
    interaction: discord.Interaction,
    status: str = None,
    user: discord.Member = None,
    limit: int = 10
):
    """View coverage records from the database"""
    
    # Check permissions
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can view database records.", ephemeral=True)
        return
    
    # Validate limit
    limit = min(max(1, limit), 20)  # Ensure limit is between 1 and 20
    
    # Get records
    records = db.get_coverage_records(
        status=status,
        user_id=user.id if user else None,
        limit=limit
    )
    
    if not records:
        await interaction.response.send_message("No coverage records found matching the criteria.", ephemeral=True)
        return
    
    # Create embed
    embed = discord.Embed(
        title="📊 Coverage Records",
        description=f"Showing up to {limit} records" + 
                   (f" for {user.mention}" if user else "") +
                   (f" with status '{status}'" if status else ""),
        color=discord.Color.blue()
    )
    
    # Add records to embed
    for record in records:
        created_at = datetime.fromisoformat(str(record['created_at']))
        expires_at = datetime.fromisoformat(str(record['expires_at'])) if record['expires_at'] else None
        
        value = f"**Type:** {record['coverage_type']}\n"
        value += f"**Duration:** {record['duration']} {'hours' if record['coverage_type'] == 'XAN' else 'jumps'}\n"
        value += f"**Cost:** {record['xanax_cost']} Xanax\n"
        value += f"**Status:** {record['status']}\n"
        value += f"**Created:** {created_at.strftime('%m/%d %H:%M')}\n"
        if expires_at:
            value += f"**Expires:** {expires_at.strftime('%m/%d %H:%M')}"
        
        embed.add_field(
            name=f"Order {record['order_id']}",
            value=value,
            inline=False
        )
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="viewtransactions", description="View transaction records from the database")
@app_commands.describe(
    type="Filter by type (received or payout)",
    user="Filter by specific user",
    limit="Number of records to show (max 20)"
)
@app_commands.choices(type=[
    app_commands.Choice(name="Received", value="received"),
    app_commands.Choice(name="Payout", value="payout")
])
async def view_transactions(
    interaction: discord.Interaction,
    type: app_commands.Choice[str] = None,
    user: discord.Member = None,
    limit: int = 10
):
    """View transaction records from the database"""
    
    # Check permissions
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can view database records.", ephemeral=True)
        return
    
    # Validate limit
    limit = min(max(1, limit), 20)  # Ensure limit is between 1 and 20
    
    # Get records
    records = db.get_transaction_records(
        transaction_type=type.value if type else None,
        user_id=user.id if user else None,
        limit=limit
    )
    
    if not records:
        await interaction.response.send_message("No transaction records found matching the criteria.", ephemeral=True)
        return
    
    # Create embed
    embed = discord.Embed(
        title="📊 Transaction Records",
        description=f"Showing up to {limit} records" + 
                   (f" for {user.mention}" if user else "") +
                   (f" of type '{type.name}'" if type else ""),
        color=discord.Color.blue()
    )
    
    # Add records to embed
    for record in records:
        transaction_time = datetime.fromisoformat(str(record['transaction_time']))
        
        value = f"**Type:** {record['transaction_type'].title()}\n"
        value += f"**Amount:** {record['amount']} Xanax\n"
        value += f"**Time:** {transaction_time.strftime('%m/%d %H:%M')}\n"
        if record['notes']:
            value += f"**Notes:** {record['notes']}"
        
        embed.add_field(
            name=f"Transaction for {record['username']}",
            value=value,
            inline=False
        )
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="costs", description="View detailed cost analysis of the insurance system")
@app_commands.describe(
    days="Number of days to analyze (leave empty for all-time stats)"
)
async def view_costs(interaction: discord.Interaction, days: int = None):
    """View detailed cost analysis of the insurance system"""
    
    # Check permissions
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can view cost analysis.", ephemeral=True)
        return
    
    # Get analysis
    analysis = db.get_cost_analysis(days)
    
    if not analysis:
        await interaction.response.send_message("❌ Failed to retrieve cost analysis.", ephemeral=True)
        return
    
    # Create embed
    period_text = f"Last {days} days" if days else "All time"
    embed = discord.Embed(
        title=f"💰 Insurance System Cost Analysis ({period_text})",
        color=discord.Color.gold()
    )
    
    # Overall stats
    received = analysis['received']
    paid = analysis['paid']
    profit = analysis['profit']
    
    embed.add_field(
        name="📥 Xanax Received",
        value=f"**Amount:** {received['total_amount']:,} Xanax\n**Transactions:** {received['total_transactions']:,}",
        inline=True
    )
    
    embed.add_field(
        name="📤 Xanax Paid Out",
        value=f"**Amount:** {paid['total_amount']:,} Xanax\n**Transactions:** {paid['total_transactions']:,}",
        inline=True
    )
    
    # Profit calculation
    profit_color = "🟢" if profit > 0 else "🔴" if profit < 0 else "⚪"
    embed.add_field(
        name="📊 System Balance",
        value=f"{profit_color} **{abs(profit):,} Xanax** {'profit' if profit >= 0 else 'loss'}",
        inline=False
    )
    
    # Top payers
    if analysis['top_payers']:
        payers_text = ""
        for i, payer in enumerate(analysis['top_payers'], 1):
            payers_text += f"{i}. **{payer['username']}**\n"
            payers_text += f"   └ {payer['total_amount']:,} Xanax ({payer['transaction_count']} payments)\n"
        
        embed.add_field(
            name="🏆 Top Insurance Buyers",
            value=payers_text or "No data",
            inline=False
        )
    
    # Top receivers
    if analysis['top_receivers']:
        receivers_text = ""
        for i, receiver in enumerate(analysis['top_receivers'], 1):
            receivers_text += f"{i}. **{receiver['username']}**\n"
            receivers_text += f"   └ {receiver['total_amount']:,} Xanax ({receiver['transaction_count']} claims)\n"
        
        embed.add_field(
            name="💫 Top Insurance Claimants",
            value=receivers_text or "No data",
            inline=False
        )
    
    # Add averages if there are transactions
    if received['total_transactions'] > 0 and paid['total_transactions'] > 0:
        avg_received = received['total_amount'] / received['total_transactions']
        avg_paid = paid['total_amount'] / paid['total_transactions']
        
        embed.add_field(
            name="📈 Averages",
            value=f"**Avg Payment:** {avg_received:.1f} Xanax\n**Avg Payout:** {avg_paid:.1f} Xanax",
            inline=False
        )
    
    current_time = datetime.now()
    embed.set_footer(text=f"Generated at {current_time.strftime('%m/%d/%Y %H:%M')}")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="stats", description="View Xanax transaction statistics")
@app_commands.describe(user="Optional: View stats for a specific user")
async def view_stats(interaction: discord.Interaction, user: discord.Member = None):
    """View Xanax transaction statistics"""
    
    if user:
        # Get stats for specific user
        received, paid = db.get_user_stats(user.id)
        title = f"📊 Xanax Statistics for {user.display_name}"
        description = f"Statistics for {user.mention}"
    else:
        # Get overall stats
        received, paid = db.get_stats()
        title = "📊 Overall Xanax Statistics"
        description = "Total Xanax transactions for all users"
    
    # Calculate balance
    balance = received - paid
    
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="💊 Xanax Received",
        value=f"{received:,} Xanax",
        inline=True
    )
    
    embed.add_field(
        name="💰 Xanax Paid Out",
        value=f"{paid:,} Xanax",
        inline=True
    )
    
    embed.add_field(
        name="⚖️ Current Balance",
        value=f"{balance:,} Xanax",
        inline=False
    )
    
    current_time = datetime.now()
    embed.set_footer(text=f"Stats as of {current_time.strftime('%m/%d/%Y %H:%M')}")
    
    await interaction.response.send_message(embed=embed)

# Auto order checking task
@tasks.loop(minutes=1)  # Check every minute, but only process based on interval
async def auto_check_orders():
    global last_check_time, auto_check_enabled, auto_check_interval
    
    if not auto_check_enabled:
        return
    
    now = datetime.now()
    if (now - last_check_time).total_seconds() < (auto_check_interval * 60):
        return
    
    last_check_time = now
    
    try:
        # Get the first guild (server) the bot is in
        guild = bot.guilds[0] if bot.guilds else None
        if not guild:
            return
            
        torn_api_key = get_api_key()
        if not torn_api_key:
            await handle_missing_api_key(guild)
            return
            
        # Get bot channel for logging
        bot_channel = discord.utils.get(guild.channels, name="bot")
        
        # Log start of check to bot channel
        if bot_channel:
            embed = discord.Embed(
                title="🔄 Auto Check Running",
                description=f"Performing automatic order verification...",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="Status",
                value=f"**Time:** {now.strftime('%m/%d %H:%M')}\n**Pending Orders:** {len(pending_order)}\n**Active Orders:** {len(active_orders)}",
                inline=False
            )
            await bot_channel.send(embed=embed)
        
        # Check for new orders from Torn API first
        new_orders_count = await detect_new_orders_from_torn(guild, torn_api_key)
        
        # Run the same order check logic as the manual command
        still_pending_count, verified_orders_count = await perform_order_check(guild, torn_api_key)
        
        # Log results to bot channel
        if bot_channel:
            if new_orders_count > 0 or verified_orders_count > 0:
                result_embed = discord.Embed(
                    title="✅ Auto Check Results",
                    description="Auto check completed with activity",
                    color=discord.Color.green()
                )
                result_embed.add_field(
                    name="Activity Found",
                    value=f"**New Orders Detected:** {new_orders_count}\n**Orders Verified & Activated:** {verified_orders_count}\n**Still Pending:** {still_pending_count}",
                    inline=False
                )
            else:
                result_embed = discord.Embed(
                    title="📋 Auto Check Complete",
                    description="No new activity found",
                    color=discord.Color.orange()
                )
                result_embed.add_field(
                    name="Status",
                    value=f"No new orders or payments detected\n**Pending Orders:** {len(pending_order)}",
                    inline=False
                )
            
            result_embed.set_footer(text=f"Next check in {auto_check_interval} minutes")
            await bot_channel.send(embed=result_embed)
            
    except Exception as e:
        print(f"Error in auto check: {e}")
        # Log error to bot channel
        guild = bot.guilds[0] if bot.guilds else None
        if guild:
            bot_channel = discord.utils.get(guild.channels, name="bot")
            if bot_channel:
                error_embed = discord.Embed(
                    title="❌ Auto Check Error",
                    description=f"Error during auto check: {str(e)}",
                    color=discord.Color.red()
                )
                try:
                    await bot_channel.send(embed=error_embed)
                except:
                    pass

async def detect_new_orders_from_torn(guild, torn_api_key):
    """Detect new insurance orders from Torn API that weren't made through Discord"""
    new_orders_count = 0
    try:
        events = await check_torn_events(torn_api_key)
        if not events:
            return new_orders_count
            
        # Look for recent events with HJSx or HJSe message codes
        current_time = datetime.now()
        lookback_limit = current_time - timedelta(hours=1)  # Only check last hour
        
        log_items = []
        if isinstance(events, dict):
            log_items = events.items()
        elif isinstance(events, list):
            log_items = [(i, entry) for i, entry in enumerate(events)]
            
        for log_id, log_entry in log_items:
            if not isinstance(log_entry, dict):
                continue
                
            # Skip if we've already processed this event
            event_id = str(log_id)
            if event_id in processed_events:
                continue
                
            log_text = log_entry.get('log', '')
            event_text = log_entry.get('event', '')
            
            # Use event text if log text is empty
            if event_text and not log_text:
                log_text = event_text
                
            if not isinstance(log_text, str):
                log_text = str(log_text)
                
            log_text_lower = log_text.lower()
            log_timestamp = log_entry.get('timestamp', 0)
            log_time = datetime.fromtimestamp(log_timestamp)
            
            # Skip old entries
            if log_time < lookback_limit:
                continue
                
            # Look for insurance orders (HJSx for XAN, HJSe for EXTC)
            # Check for Xanax transfers with correct message codes
            has_xanax = 'xanax' in log_text_lower
            has_hjsx = 'hjsx' in log_text_lower
            has_hjse = 'hjse' in log_text_lower
            # Fix transfer detection - handle both "You were sent" and "sent...to you" formats
            has_transfer = (('sent' in log_text_lower and 'to you' in log_text_lower) or 
                          'you were sent' in log_text_lower or 
                          'received' in log_text_lower)
            
            is_xan_order = has_xanax and has_hjsx and has_transfer
            is_extc_order = has_xanax and has_hjse and has_transfer
            
            # Debug: Print details if we find potential matches
            if has_xanax or has_hjsx or has_hjse:
                print(f"DEBUG: Found potential match in event {event_id}")
                print(f"  Text: {log_text}")
                print(f"  Has Xanax: {has_xanax}")
                print(f"  Has HJSx: {has_hjsx}")
                print(f"  Has HJSe: {has_hjse}")
                print(f"  Has transfer: {has_transfer}")
                print(f"  XAN match: {is_xan_order}")
                print(f"  EXTC match: {is_extc_order}")
                            
            if not (is_xan_order or is_extc_order):
                continue
                
            # Extract sender name from the event text
            sender_name = None
            if 'from' in log_text_lower:
                # Try to extract name from patterns like "from <a href=...>Name</a>"
                import re
                name_match = re.search(r'from.*?>([^<]+)</a>', log_text)
                if name_match:
                    sender_name = name_match.group(1).strip()
                else:
                    # Fallback: try to extract from plain text
                    parts = log_text.split(' from ')
                    if len(parts) > 1:
                        name_part = parts[1].split(' with')[0].strip()
                        sender_name = name_part.split()[0]  # Take first word as name
                        
            if not sender_name:
                continue
                
            # Check if sender exists in Discord server
            discord_member = None
            for member in guild.members:
                # Check if nickname matches (case insensitive)
                member_display = member.display_name.lower()
                if sender_name.lower() in member_display or member_display in sender_name.lower():
                    discord_member = member
                    break
                    
            if not discord_member:
                continue  # Skip if sender not found in Discord
                
            # Check if this person already has a pending order
            existing_pending_order = any(order_data.get('user_id') == discord_member.id 
                                       for order_data in pending_order.values())
            if existing_pending_order:
                continue  # Skip if they already have a pending order
                
            # Check if this person already has an active order (insurance contract)
            existing_active_order = any(order_data.get('user_id') == discord_member.id 
                                      for order_data in active_orders.values())
            if existing_active_order:
                continue  # Skip if they already have active insurance coverage
                
            # Extract payment amount - handle both "some Xanax" (=1) and "4x Xanax" formats
            payment_amount = 0
            
            # First try to find "Zx Xanax" pattern
            xanax_pattern = re.search(r'(\d+)x?\s*xanax', log_text_lower)
            if xanax_pattern:
                payment_amount = int(xanax_pattern.group(1))
            elif 'some xanax' in log_text_lower:
                payment_amount = 1  # "some" means 1
            else:
                # Fallback: look for any numbers in the text
                numbers_in_text = re.findall(r'\d+', log_text)
                if numbers_in_text:
                    payment_amount = int(numbers_in_text[0])
            
            print(f"DEBUG: Extracted payment amount: {payment_amount}")
            
            if payment_amount == 0:
                print("DEBUG: No valid payment amount found, skipping")
                continue  # Skip if no valid payment amount found
                
            # Determine coverage type and calculate coverage details
            coverage_type = 'XAN' if is_xan_order else 'EXTC'
            
            if coverage_type == 'XAN':
                # Find matching XAN pricing in config
                hours = None
                xanax_reward = None
                
                for duration, price_info in pricing_config['xan'].items():
                    if price_info['cost'] == payment_amount:
                        hours = duration
                        xanax_reward = price_info['reward']
                        break
                
                if hours is None:
                    continue  # Payment doesn't match any configured pricing
                    
            else:
                # EXTC: Find matching pricing in config
                jumps = None
                edvds_reward = None
                xanax_reward = None
                ecstasy_reward = None
                
                for jump_count, price_info in pricing_config['extc'].items():
                    if price_info['cost'] == payment_amount:
                        jumps = jump_count
                        edvds_reward = price_info['edvds']
                        xanax_reward = price_info['xanax']
                        ecstasy_reward = price_info['ecstasy']
                        break
                
                if jumps is None:
                    continue  # Payment doesn't match any configured pricing
                    
                hours = 2  # EXTC is always 2H
                
            # Create new order
            order_id = f"{discord_member.id}_{datetime.now().timestamp()}_auto"
            
            order_data = {
                "user_id": discord_member.id,
                "username": str(discord_member),
                "display_name": discord_member.display_name,
                "coverage_type": coverage_type,
                "timestamp": log_time.strftime('%Y-%m-%d %H:%M:%S'),
                "xanax_payment": payment_amount,
                "xanax_reward": xanax_reward,
                "payment_received_at": log_time.strftime('%Y-%m-%d %H:%M:%S'),
                "auto_detected": True,
                "torn_sender_name": sender_name
            }
            
            if coverage_type == 'XAN':
                order_data["hours"] = hours
            else:  # EXTC
                order_data["jumps"] = jumps
                order_data["edvds_reward"] = edvds_reward
                order_data["ecstasy_reward"] = ecstasy_reward
                
                # Add to pending orders for verification
                pending_order[order_id] = order_data
                
                # Mark event as processed
                processed_events.add(event_id)
                
                # Increment counter
                new_orders_count += 1
                
                # Log to order channel
                order_channel = discord.utils.get(guild.channels, name="order")
                if order_channel:
                    embed = discord.Embed(
                        title="🔍 Auto-Detected Order",
                        description=f"Detected insurance payment from **{sender_name}**",
                        color=discord.Color.gold()
                    )
                    if coverage_type == 'XAN':
                        reward_text = f"{xanax_reward} Xanax"
                        coverage_text = f"{hours}H Xanax"
                    else:  # EXTC
                        reward_text = f"{edvds_reward} eDVDs, {xanax_reward} Xanax, {ecstasy_reward} Ecstasy"
                        coverage_text = f"{jumps} Jump{'s' if jumps > 1 else ''} Ecstasy (2H)"
                    
                    embed.add_field(
                        name="Details",
                        value=f"**Discord User:** {discord_member.mention}\n**Coverage:** {coverage_text}\n**Payment:** {payment_amount} Xanax\n**Reward:** {reward_text}",
                        inline=False
                    )
                    embed.add_field(
                        name="Status",
                        value="Added to pending orders for verification",
                        inline=False
                    )
                    embed.set_footer(text=f"Auto-detected at {log_time.strftime('%m/%d %H:%M')}")
                    
                    try:
                        await order_channel.send(embed=embed)
                    except:
                        pass  # Ignore channel permission errors
                        
    except Exception as e:
        print(f"Error detecting new orders: {e}")
        
    return new_orders_count

async def process_pending_orders(guild, torn_api_key):
    """Process existing pending orders automatically"""
    verified_count = 0
    try:
        events = await check_torn_events(torn_api_key)
        if not events:
            return verified_count
            
        verified_orders = []
        
        # Use existing order verification logic
        current_time = datetime.now()
        lookback_limit = current_time - timedelta(hours=24)
        
        for order_id, order_data in list(pending_order.items()):
            coverage_type = order_data.get('coverage_type', 'XAN')
            message_code = 'HJSx' if coverage_type == 'XAN' else 'HJSe'
            username = order_data.get('username', 'Unknown')
            display_name = order_data.get('display_name', username)
            expected_payment = order_data.get('xanax_payment', 0)
            display_name_clean = display_name.split('[')[0].strip() if '[' in display_name else display_name
            
            payment_found = False
            matching_event = None
            
            log_items = []
            if isinstance(events, dict):
                log_items = events.items()
            elif isinstance(events, list):
                log_items = [(i, entry) for i, entry in enumerate(events)]
            
            for log_id, log_entry in log_items:
                if not isinstance(log_entry, dict):
                    continue
                    
                log_text = log_entry.get('log', '')
                event_text = log_entry.get('event', '')
                
                if event_text and not log_text:
                    log_text = event_text
                
                if not isinstance(log_text, str):
                    log_text = str(log_text)
                    
                log_text_lower = log_text.lower()
                log_timestamp = log_entry.get('timestamp', 0)
                log_time = datetime.fromtimestamp(log_timestamp)
                
                if log_time < lookback_limit:
                    continue
                
                # Check for Xanax transfer with message code
                has_xanax = 'xanax' in log_text_lower
                has_message_code = message_code.lower() in log_text_lower
                # Fix transfer detection - handle both "You were sent" and "sent...to you" formats
                has_transfer = (('sent' in log_text_lower and 'to you' in log_text_lower) or 
                              'you were sent' in log_text_lower or 
                              'received' in log_text_lower)
                
                if has_xanax and has_message_code and has_transfer:
                    
                    # Verify payment amount - handle both "some Xanax" and "Zx Xanax" formats
                    payment_amount_found = False
                    
                    # First try to find "Zx Xanax" pattern
                    xanax_pattern = re.search(r'(\d+)x?\s*xanax', log_text_lower)
                    if xanax_pattern:
                        found_amount = int(xanax_pattern.group(1))
                        if found_amount == expected_payment:
                            payment_amount_found = True
                    elif 'some xanax' in log_text_lower and expected_payment == 1:
                        payment_amount_found = True  # "some" means 1
                    else:
                        # Fallback: look for any numbers in the text
                        numbers_in_text = re.findall(r'\d+', log_text)
                        payment_amount_found = any(int(num) == expected_payment for num in numbers_in_text)
                    
                    display_name_found = display_name_clean.lower() in log_text_lower
                    username_found = username.lower() in log_text_lower
                    
                    display_name_words = display_name_clean.lower().split()
                    username_words = username.lower().split()
                    
                    partial_display_match = any(word in log_text_lower for word in display_name_words if len(word) > 2)
                    partial_username_match = any(word in log_text_lower for word in username_words if len(word) > 2)
                    
                    name_match_found = display_name_found or username_found or partial_display_match or partial_username_match
                    
                    order_time = datetime.strptime(order_data.get('timestamp'), '%Y-%m-%d %H:%M:%S')
                    time_difference = abs((log_time - order_time).total_seconds())
                    time_valid = time_difference <= 3600
                    
                    if time_valid and payment_amount_found and name_match_found:
                        payment_found = True
                        matching_event = {
                            'log': log_entry.get('log', ''),
                            'event_text': event_text,
                            'timestamp': log_time,
                            'log_id': log_id,
                            'verified_amount': expected_payment,
                            'verified_user': True,
                            'matched_name': display_name_clean if display_name_found else username
                        }
                        order_data['payment_received_at'] = log_time.strftime('%Y-%m-%d %H:%M:%S')
                        if log_time < order_time:
                            order_data['timestamp'] = log_time.strftime('%Y-%m-%d %H:%M:%S')
                        break
            
            if payment_found:
                verified_orders.append({
                    'order_id': order_id,
                    'order_data': order_data,
                    'payment_event': matching_event,
                    'message_code': message_code
                })
        
        # Process verified orders
        if verified_orders:
            order_channel = discord.utils.get(guild.channels, name="order")
            
            for order in verified_orders:
                order_id = order['order_id']
                order_data = order['order_data']
                
                # Move to active orders
                active_orders[order_id] = order_data.copy()
                active_orders[order_id]['activated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # Remove from pending
                if order_id in pending_order:
                    del pending_order[order_id]
                
                # Increment counter
                verified_count += 1
                
                # Log activation to order channel
                if order_channel:
                    display_name = order_data.get('display_name', order_data.get('username', 'Unknown'))
                    coverage_type = order_data.get('coverage_type', 'XAN')
                    auto_detected = order_data.get('auto_detected', False)
                    
                    embed = discord.Embed(
                        title="✅ Insurance Activated (Auto)",
                        description=f"**{display_name}** insurance is now active",
                        color=discord.Color.green()
                    )
                    
                    if coverage_type == 'XAN':
                        hours = order_data.get('hours', 24)
                        reward = order_data.get('xanax_reward', 0)
                        embed.add_field(
                            name="Coverage Details",
                            value=f"**Type:** Xanax Overdose\n**Duration:** {hours} hours\n**Payout:** {reward} Xanax",
                            inline=False
                        )
                    else:
                        jumps = order_data.get('jumps', 1)
                        reward = order_data.get('xanax_reward', 0)
                        embed.add_field(
                            name="Coverage Details",
                            value=f"**Type:** Ecstasy Overdose\n**Jumps:** {jumps}\n**Payout:** {reward} Xanax per jump",
                            inline=False
                        )
                    
                    status_text = "Auto-verified payment" + (" (auto-detected)" if auto_detected else "")
                    embed.add_field(name="Status", value=status_text, inline=False)
                    embed.set_footer(text=f"Activated: {datetime.now().strftime('%m/%d %H:%M')}")
                    
                    try:
                        await order_channel.send(embed=embed)
                    except:
                        pass
                        
    except Exception as e:
        print(f"Error processing pending orders: {e}")
        
    return verified_count

async def xan_coverage_autocomplete(interaction: discord.Interaction, current: str):
    """Autocomplete for XAN coverage options based on configured pricing"""
    global pricing_config
    choices = []
    for hours in sorted(pricing_config['xan'].keys()):
        name = f"{hours}H Coverage"
        if current.lower() in name.lower():
            choices.append(app_commands.Choice(name=name, value=str(hours)))
    return choices[:25]  # Discord limit

@bot.tree.command(name="xan", description="Insure yourself in case of xan overdose")
@app_commands.describe(coverage="Select insurance coverage duration")
@app_commands.autocomplete(coverage=xan_coverage_autocomplete)
async def xan_insurance(interaction: discord.Interaction, coverage: str):
    """Handle the /xan insurance command"""
    global pricing_config
    
    user = interaction.user
    guild = interaction.guild
    
    # Check if XAN pricing is configured
    if not pricing_config['xan']:
        embed = discord.Embed(
            title="⚠️ No Pricing Configured",
            description="XAN insurance pricing has not been set up yet.",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="Administrator Notice",
            value="Admins can configure pricing using `/setxanprice`",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Check if user already has pending or active orders
    user_id = user.id
    
    # Check for existing pending orders
    existing_pending = any(order_data.get('user_id') == user_id for order_data in pending_order.values())
    if existing_pending:
        embed = discord.Embed(
            title="⚠️ Order Already Exists",
            description="You already have a pending Xanax insurance order!",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="Current Status",
            value="Please wait for your current order to be processed before placing a new one.",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Check for existing active orders
    existing_active = any(order_data.get('user_id') == user_id for order_data in active_orders.values())
    if existing_active:
        embed = discord.Embed(
            title="🛡️ Insurance Already Active",
            description="You already have active Xanax insurance coverage!",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Current Status",
            value="Your insurance is currently active. Use `/check` to see your coverage details.",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Calculate costs and rewards based on dynamic pricing
    hours = int(coverage)
    
    # Get pricing from config
    if hours not in pricing_config['xan']:
        await interaction.response.send_message("❌ Invalid coverage duration selected.", ephemeral=True)
        return
    
    price_config = pricing_config['xan'][hours]
    xanax_payment = price_config['cost']
    xanax_reward = price_config['reward']
    
    # Create insurance embed
    embed = discord.Embed(
        title="🔒 Xanax Insurance Order",
        description=f"**Coverage Duration:** {hours} hours\n**Payment Required:** {xanax_payment} Xanax",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="💊 Payment Instructions",
        value=f"Send **{xanax_payment} Xanax** to [Danieltrsl](https://www.torn.com/profiles.php?XID=2823859)\n⚠️ **Include message: HJSx** - Payments without this message will be voided!",
        inline=False
    )
    embed.add_field(
        name="🎁 In the Event of Overdose",
        value=f"You will be rewarded **{xanax_reward} Xanax**",
        inline=False
    )
    embed.add_field(
        name="📋 Order Details",
        value=f"**User:** {user.mention}\n**Date/Time:** {datetime.now().strftime('%m/%d %H:%M')}\n**Status:** Pending",
        inline=False
    )
    embed.set_footer(text="Your insurance will be active once payment is confirmed")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    
    # Get the message for future updates
    user_message = await interaction.original_response()
    
    # Log order to order channel
    order_channel = discord.utils.get(guild.channels, name="order")
    if order_channel:
        # Use server nickname if available, otherwise username
        display_name = user.display_name if hasattr(user, 'display_name') else user.name
        
        log_embed = discord.Embed(
            title="📋 New Xanax Insurance Order",
            description=f"{user.mention} (**{display_name}**) selected **{hours}H** coverage at **{datetime.now().strftime('%m/%d %H:%M')}**",
            color=discord.Color.orange()
        )
        log_embed.add_field(
            name="Details",
            value=f"**Payment:** {xanax_payment} Xanax\n**Reward:** {xanax_reward} Xanax\n**Status:** Pending",
            inline=False
        )
        log_embed.set_footer(text=f"User ID: {user.id} | Server Name: {display_name}")
        await order_channel.send(embed=log_embed)
    
    # Store pending order
    order_id = f"{user.id}_{datetime.now().timestamp()}"
    order_data = {
        "order_id": order_id,
        "user_id": user.id,
        "username": str(user),
        "display_name": user.display_name if hasattr(user, 'display_name') else user.name,
        "coverage_type": "XAN",
        "hours": hours,
        "xanax_payment": xanax_payment,
        "xanax_reward": xanax_reward,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "status": "pending",
        "user_message": user_message  # Store message for updates
    }
    pending_order[order_id] = order_data
    
    # Record in database
    db.add_coverage(order_data)

async def extc_coverage_autocomplete(interaction: discord.Interaction, current: str):
    """Autocomplete for EXTC coverage options based on configured pricing"""
    global pricing_config
    choices = []
    for jumps in sorted(pricing_config['extc'].keys()):
        name = f"{jumps} Jump Coverage" if jumps == 1 else f"{jumps} Jump Coverage"
        if current.lower() in name.lower():
            choices.append(app_commands.Choice(name=name, value=str(jumps)))
    return choices[:25]  # Discord limit

@bot.tree.command(name="extc", description="Insure yourself in case of ecstasy overdose")
@app_commands.describe(coverage="Select ecstasy insurance coverage")
@app_commands.autocomplete(coverage=extc_coverage_autocomplete)
async def extc_insurance(interaction: discord.Interaction, coverage: str):
    """Handle the /extc ecstasy insurance command"""
    global pricing_config
    
    user = interaction.user
    guild = interaction.guild
    
    # Check if EXTC pricing is configured
    if not pricing_config['extc']:
        embed = discord.Embed(
            title="⚠️ No Pricing Configured",
            description="EXTC insurance pricing has not been set up yet.",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="Administrator Notice", 
            value="Admins can configure pricing using `/setextcprice`",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Check if user already has pending or active orders
    user_id = user.id
    
    # Check for existing pending orders
    existing_pending = any(order_data.get('user_id') == user_id for order_data in pending_order.values())
    if existing_pending:
        embed = discord.Embed(
            title="⚠️ Order Already Exists",
            description="You already have a pending Ecstasy insurance order!",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="Current Status",
            value="Please wait for your current order to be processed before placing a new one.",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Check for existing active orders
    existing_active = any(order_data.get('user_id') == user_id for order_data in active_orders.values())
    if existing_active:
        embed = discord.Embed(
            title="🛡️ Insurance Already Active",
            description="You already have active Ecstasy insurance coverage!",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Current Status",
            value="Your insurance is currently active. Use `/check` to see your coverage details.",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Calculate payment and rewards based on dynamic pricing
    jumps = int(coverage)
    
    # Get pricing from config
    if jumps not in pricing_config['extc']:
        await interaction.response.send_message("❌ Invalid coverage option selected.", ephemeral=True)
        return
    
    price_config = pricing_config['extc'][jumps]
    xanax_payment = price_config['cost']
    edvds_reward = price_config['edvds']
    xanax_reward = price_config['xanax']
    ecstasy_reward = price_config['ecstasy']
    
    # Create insurance embed
    embed = discord.Embed(
        title="💊 Ecstasy Insurance Order",
        description=f"**Coverage:** {jumps} Jump{'s' if jumps > 1 else ''}\n**Payment Required:** {xanax_payment} Xanax",
        color=discord.Color.purple()
    )
    embed.add_field(
        name="💰 Payment Instructions",
        value=f"Send **{xanax_payment} Xanax** to [Danieltrsl](https://www.torn.com/profiles.php?XID=2823859)\n⚠️ **Include message: HJSe** - Payments without this message will be voided!",
        inline=False
    )
    embed.add_field(
        name="🎁 In the Event of Overdose",
        value=f"You will be rewarded:\n• **{edvds_reward} eDVDs**\n• **{xanax_reward} Xanax**\n• **{ecstasy_reward} Ecstasy**",
        inline=False
    )
    embed.add_field(
        name="📋 Order Details",
        value=f"**User:** {user.mention}\n**Date/Time:** {datetime.now().strftime('%m/%d %H:%M')}\n**Status:** Pending",
        inline=False
    )
    embed.set_footer(text="Your ecstasy insurance will be active once payment is confirmed")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    
    # Get the message for future updates
    user_message = await interaction.original_response()
    
    # Log order to order channel
    order_channel = discord.utils.get(guild.channels, name="order")
    if order_channel:
        # Use server nickname if available, otherwise username
        display_name = user.display_name if hasattr(user, 'display_name') else user.name
        
        log_embed = discord.Embed(
            title="💊 New Ecstasy Insurance Order",
            description=f"{user.mention} (**{display_name}**) selected **{jumps} Jump** EXTC coverage at **{datetime.now().strftime('%m/%d %H:%M')}**",
            color=discord.Color.purple()
        )
        log_embed.add_field(
            name="Details",
            value=f"**Payment:** {xanax_payment} Xanax\n**Reward:** {edvds_reward} eDVDs, {xanax_reward} Xanax, {ecstasy_reward} Ecstasy\n**Status:** Pending",
            inline=False
        )
        log_embed.set_footer(text=f"User ID: {user.id} | Server Name: {display_name}")
        await order_channel.send(embed=log_embed)
    
    # Store pending order
    order_id = f"{user.id}_{datetime.now().timestamp()}"
    pending_order[order_id] = {
        "user_id": user.id,
        "username": str(user),
        "display_name": user.display_name if hasattr(user, 'display_name') else user.name,
        "coverage_type": "EXTC",
        "jumps": jumps,
        "xanax_payment": xanax_payment,
        "edvds_reward": edvds_reward,
        "xanax_reward": xanax_reward,
        "ecstasy_reward": ecstasy_reward,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "status": "pending",
        "user_message": user_message  # Store message for updates
    }

async def check_torn_events(api_key, user_id=None):
    """Check Torn events for item transfers"""
    try:
        # Use the events endpoint which should have more detailed information
        url = f"https://api.torn.com/user/?selections=events&key={api_key}"
        if user_id:
            url = f"https://api.torn.com/user/{user_id}?selections=events&key={api_key}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if 'error' in data:
                        print(f"Torn API Error: {data['error']}")
                        return None
                    return data.get('events', {})
                else:
                    print(f"HTTP Error: {response.status}")
                    return None
    except Exception as e:
        print(f"Error checking Torn events: {e}")
        return None

@bot.tree.command(name="apikeyadd", description="Set the Torn API key for the bot (Admin only)")
@app_commands.describe(api_key="Your Torn API key")
async def add_api_key(interaction: discord.Interaction, api_key: str):
    """Set the Torn API key for the bot"""
    
    # Check if user is admin
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can set the API key.", ephemeral=True)
        return
    
    global stored_api_key
    
    # Basic validation - check if it looks like a valid API key
    if len(api_key) < 10:
        await interaction.response.send_message("❌ Invalid API key format. Please provide a valid Torn API key.", ephemeral=True)
        return
    
    # Test the API key by making a basic call
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.torn.com/user/?selections=basic&key={api_key}"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if 'error' in data:
                        await interaction.response.send_message(f"❌ Invalid API key: {data['error']}", ephemeral=True)
                        return
                    
                    # API key is valid, store it
                    stored_api_key = api_key
                    username = data.get('name', 'Unknown')
                    user_id = data.get('player_id', 'Unknown')
                    
                    embed = discord.Embed(
                        title="✅ API Key Added Successfully",
                        description="Torn API key has been configured",
                        color=discord.Color.green()
                    )
                    embed.add_field(
                        name="Account Information",
                        value=f"**Name:** {username}\n**ID:** {user_id}",
                        inline=False
                    )
                    embed.set_footer(text=f"Set by: {interaction.user.display_name}")
                    
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                else:
                    await interaction.response.send_message(f"❌ Failed to validate API key. HTTP Error: {response.status}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Error validating API key: {str(e)}", ephemeral=True)

@bot.tree.command(name="setxanprice", description="Set XAN insurance pricing (Admin only)")
@app_commands.describe(
    hours="Coverage duration in hours (any positive number)",
    cost="Cost in Xanax",
    reward="Reward payout in Xanax"
)
async def set_xan_price(interaction: discord.Interaction, hours: int, cost: int, reward: int):
    """Set XAN insurance pricing"""
    
    # Check if user is admin
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can set pricing.", ephemeral=True)
        return
    
    global pricing_config
    
    # Validation
    if hours < 1 or cost < 1 or reward < 1:
        await interaction.response.send_message("❌ Hours, cost, and reward must be at least 1.", ephemeral=True)
        return
    
    # Update pricing
    pricing_config['xan'][hours] = {'cost': cost, 'reward': reward}
    
    embed = discord.Embed(
        title="✅ XAN Pricing Updated",
        description=f"Updated pricing for {hours}H coverage",
        color=discord.Color.green()
    )
    embed.add_field(
        name="New Pricing",
        value=f"**Duration:** {hours} hours\n**Cost:** {cost} Xanax\n**Reward:** {reward} Xanax",
        inline=False
    )
    embed.set_footer(text=f"Updated by: {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="setextcprice", description="Set EXTC insurance pricing (Admin only)")
@app_commands.describe(
    jumps="Number of jumps to cover (any positive number)",
    cost="Cost in Xanax",
    edvds_reward="eDVDs reward payout",
    xanax_reward="Xanax reward payout", 
    ecstasy_reward="Ecstasy reward payout"
)
async def set_extc_price(interaction: discord.Interaction, jumps: int, cost: int, edvds_reward: int, xanax_reward: int, ecstasy_reward: int):
    """Set EXTC insurance pricing"""
    
    # Check if user is admin
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can set pricing.", ephemeral=True)
        return
    
    global pricing_config
    
    # Validation
    if jumps < 1 or cost < 1 or edvds_reward < 1 or xanax_reward < 1 or ecstasy_reward < 1:
        await interaction.response.send_message("❌ All values must be at least 1.", ephemeral=True)
        return
    
    # Update pricing
    pricing_config['extc'][jumps] = {
        'cost': cost, 
        'edvds': edvds_reward, 
        'xanax': xanax_reward, 
        'ecstasy': ecstasy_reward
    }
    
    embed = discord.Embed(
        title="✅ EXTC Pricing Updated",
        description=f"Updated pricing for {jumps} jump coverage",
        color=discord.Color.green()
    )
    embed.add_field(
        name="New Pricing",
        value=f"**Coverage:** {jumps} jump(s)\n**Cost:** {cost} Xanax\n**Rewards:** {edvds_reward} eDVDs, {xanax_reward} Xanax, {ecstasy_reward} Ecstasy",
        inline=False
    )
    embed.set_footer(text=f"Updated by: {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="viewpricing", description="View current insurance pricing (Admin only)")
async def view_pricing(interaction: discord.Interaction):
    """View current pricing configuration"""
    
    # Check if user is admin
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can view pricing.", ephemeral=True)
        return
    
    global pricing_config
    
    embed = discord.Embed(
        title="💰 Current Insurance Pricing",
        description="Active pricing configuration",
        color=discord.Color.blue()
    )
    
    # XAN pricing
    xan_text = ""
    if pricing_config['xan']:
        for hours in sorted(pricing_config['xan'].keys()):
            config = pricing_config['xan'][hours]
            xan_text += f"**{hours}H:** {config['cost']} Xanax → {config['reward']} Xanax\n"
    else:
        xan_text = "*No XAN pricing configured*\nUse `/setxanprice` to add options"
    
    embed.add_field(
        name="💊 XAN Insurance",
        value=xan_text,
        inline=True
    )
    
    # EXTC pricing  
    extc_text = ""
    if pricing_config['extc']:
        for jumps in sorted(pricing_config['extc'].keys()):
            config = pricing_config['extc'][jumps]
            extc_text += f"**{jumps}J:** {config['cost']} Xanax → {config['edvds']} eDVDs, {config['xanax']} Xanax, {config['ecstasy']} Ecstasy\n"
    else:
        extc_text = "*No EXTC pricing configured*\nUse `/setextcprice` to add options"
    
    embed.add_field(
        name="🌟 EXTC Insurance",
        value=extc_text,
        inline=True
    )
    
    embed.set_footer(text=f"Viewed by: {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

def get_api_key():
    """Get the current API key (only from stored, no fallback to .env)"""
    global stored_api_key
    return stored_api_key

async def handle_missing_api_key(guild):
    """Handle missing API key by posting message to #bot channel"""
    if not guild:
        return False
        
    bot_channel = discord.utils.get(guild.channels, name="bot")
    if bot_channel:
        embed = discord.Embed(
            title="⚠️ No Torn API Key Configured",
            description="Bot operations requiring Torn API access are disabled.",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="Required Action",
            value="An administrator must configure the Torn API key using `/apikeyadd`",
            inline=False
        )
        embed.add_field(
            name="Affected Features",
            value="• Order verification\n• Auto-check\n• Payment detection\n• API debugging/testing",
            inline=False
        )
        try:
            await bot_channel.send(embed=embed)
        except:
            pass  # Ignore channel permission errors
    return False

@bot.tree.command(name="debugapi", description="Debug Torn API events for specific user (Admin only)")
@app_commands.describe(search_term="Search for specific text in events (optional)")
async def debug_api(interaction: discord.Interaction, search_term: str = ""):
    """Debug the Torn API events to see raw data"""
    
    # Check if user is admin
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can debug the API.", ephemeral=True)
        return
    
    # Get API key from environment
    torn_api_key = get_api_key()
    if not torn_api_key:
        await interaction.response.send_message("❌ Torn API key not configured! Use /apikeyadd to set it.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        events = await check_torn_events(torn_api_key)
        if not events:
            await interaction.followup.send("❌ No events returned from API")
            return
            
        # Get recent events (last 10)
        debug_info = []
        debug_info.append(f"**Total events:** {len(events)}")
        debug_info.append(f"**Events type:** {type(events).__name__}")
        
        # Process recent events
        log_items = []
        if isinstance(events, dict):
            log_items = list(events.items())[:10]  # Get first 10
        elif isinstance(events, list):
            log_items = [(i, entry) for i, entry in enumerate(events[:10])]
        
        found_matches = 0
        for i, (log_id, log_entry) in enumerate(log_items):
            if not isinstance(log_entry, dict):
                continue
                
            log_text = log_entry.get('log', '')
            event_text = log_entry.get('event', '')
            timestamp = log_entry.get('timestamp', 0)
            category = log_entry.get('category', 'Unknown')
            
            # Use event text if log text is empty
            if event_text and not log_text:
                log_text = event_text
                
            if not isinstance(log_text, str):
                log_text = str(log_text)
                
            # Check if this matches our search or contains relevant keywords
            search_match = (not search_term or 
                          search_term.lower() in log_text.lower() or 
                          'xanax' in log_text.lower() or 
                          'hjsx' in log_text.lower() or 
                          'hjse' in log_text.lower())
            
            if search_match:
                found_matches += 1
                time_str = datetime.fromtimestamp(timestamp).strftime('%m/%d %H:%M') if timestamp else "No timestamp"
                debug_info.append(f"\n**Event {i+1}:** ID={log_id}")
                debug_info.append(f"**Time:** {time_str}")
                debug_info.append(f"**Category:** {category}")
                debug_info.append(f"**Log:** {log_text[:200]}...")
                if event_text and event_text != log_text:
                    debug_info.append(f"**Event:** {event_text[:200]}...")
                debug_info.append("---")
        
        debug_info.append(f"\n**Matching events found:** {found_matches}")
        
        # Create embed with debug info
        embed = discord.Embed(
            title="🔍 API Debug Results",
            description=f"Debugging Torn API events{f' (searching: {search_term})' if search_term else ''}",
            color=discord.Color.blue()
        )
        
        debug_text = "\n".join(debug_info[:50])  # Limit to prevent embed overflow
        if len(debug_text) > 4000:
            debug_text = debug_text[:4000] + "...(truncated)"
            
        embed.add_field(
            name="Debug Information",
            value=debug_text,
            inline=False
        )
        
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Debug Failed: {str(e)}")

@bot.tree.command(name="testapi", description="Test Torn API connection (Admin only)")
async def test_api(interaction: discord.Interaction):
    """Test the Torn API connection"""
    
    # Check if user is admin
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can test the API.", ephemeral=True)
        return
    
    # Get API key from environment
    torn_api_key = get_api_key()
    if not torn_api_key:
        await interaction.response.send_message("❌ Torn API key not configured! Use /apikeyadd to set it.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    # Test API call
    try:
        async with aiohttp.ClientSession() as session:
            # Test basic user info first
            url = f"https://api.torn.com/user/?selections=basic&key={torn_api_key}"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if 'error' in data:
                        error_info = data.get('error', {})
                        if isinstance(error_info, dict):
                            await interaction.followup.send(f"❌ API Error: {error_info.get('error', 'Unknown error')}")
                        else:
                            await interaction.followup.send(f"❌ API Error: {error_info}")
                        return
                    
                    username = data.get('name', 'Unknown')
                    user_id = data.get('player_id', 'Unknown')
                    
                    # Now test log endpoint
                    # Try using events API instead of log API for better data
                    log_url = f"https://api.torn.com/user/?selections=events&key={torn_api_key}"
                    async with session.get(log_url) as log_response:
                        if log_response.status == 200:
                            log_data = await log_response.json()
                            if 'error' in log_data:
                                error_info = log_data.get('error', {})
                                if isinstance(error_info, dict):
                                    await interaction.followup.send(f"❌ Log API Error: {error_info.get('error', 'Unknown error')}")
                                else:
                                    await interaction.followup.send(f"❌ Log API Error: {error_info}")
                                return
                            
                            log_entries = log_data.get('events', {})
                            
                            # Handle different log data formats
                            recent_entries = []
                            log_count = 0
                            
                            try:
                                if isinstance(log_entries, dict):
                                    log_count = len(log_entries)
                                    # Dictionary format: {id: {log_data}} - handle both string and int keys
                                    items_to_process = list(log_entries.items())[:5]
                                    recent_entries.append(f"Processing {len(items_to_process)} entries from {log_count} total")
                                    
                                    for i, (log_id, log_entry) in enumerate(items_to_process):
                                        try:
                                            recent_entries.append(f"Entry {i+1}: ID={log_id} (type: {type(log_id).__name__}), Value type: {type(log_entry).__name__}")
                                            
                                            if isinstance(log_entry, dict):
                                                timestamp = log_entry.get('timestamp', 0)
                                                log_text = log_entry.get('log', 'No log text')
                                                category = log_entry.get('category', 'Unknown')
                                                
                                                if timestamp:
                                                    time_str = datetime.fromtimestamp(timestamp).strftime('%m/%d %H:%M')
                                                else:
                                                    time_str = 'No timestamp'
                                                
                                                recent_entries.append(f"**{time_str}** [{category}]: {str(log_text)[:100]}...")
                                            else:
                                                recent_entries.append(f"Non-dict entry: {str(log_entry)[:100]}")
                                        except Exception as entry_error:
                                            recent_entries.append(f"Entry {i+1} error: {str(entry_error)}")
                                            
                                elif isinstance(log_entries, list):
                                    log_count = len(log_entries)
                                    # List format: [{log_data}]
                                    for i, log_entry in enumerate(log_entries[:5]):
                                        try:
                                            if isinstance(log_entry, dict):
                                                timestamp = log_entry.get('timestamp', 0)
                                                log_text = log_entry.get('log', 'No log text')
                                                category = log_entry.get('category', 'Unknown')
                                                
                                                if timestamp:
                                                    time_str = datetime.fromtimestamp(timestamp).strftime('%m/%d %H:%M')
                                                else:
                                                    time_str = 'No timestamp'
                                                
                                                recent_entries.append(f"**{time_str}** [{category}]: {str(log_text)[:100]}...")
                                            else:
                                                recent_entries.append(f"Non-dict list entry: {str(log_entry)[:100]}")
                                        except Exception as entry_error:
                                            recent_entries.append(f"List entry {i+1} error: {str(entry_error)}")
                                else:
                                    recent_entries.append(f"Unexpected log format: {type(log_entries)} - {str(log_entries)[:200]}")
                            except Exception as parse_error:
                                recent_entries.append(f"Parse error: {str(parse_error)}")
                                import traceback
                                recent_entries.append(f"Traceback: {traceback.format_exc()[:200]}")
                            
                            embed = discord.Embed(
                                title="✅ Torn API Test Results",
                                description=f"API connection successful!",
                                color=discord.Color.green()
                            )
                            embed.add_field(
                                name="Account Info",
                                value=f"**Name:** {username}\n**ID:** {user_id}",
                                inline=False
                            )
                            embed.add_field(
                                name="Log Data Info",
                                value=f"**Log entries type:** {type(log_entries).__name__}\n**Count:** {log_count}",
                                inline=False
                            )
                            
                            if recent_entries:
                                embed.add_field(
                                    name="Recent Log Entries (for debugging)",
                                    value="\n".join(recent_entries[:3]),  # Show first 3
                                    inline=False
                                )
                            
                            await interaction.followup.send(embed=embed)
                        else:
                            await interaction.followup.send(f"❌ Log API HTTP Error: {log_response.status}")
                else:
                    await interaction.followup.send(f"❌ Basic API HTTP Error: {response.status}")
    except Exception as e:
        await interaction.followup.send(f"❌ API Test Failed: {str(e)}")

async def perform_order_check(guild, torn_api_key):
    """Perform order checking logic (used by both manual and auto check)"""
    if not pending_order:
        return 0, 0  # no pending orders, no verified orders
    
    # Check events for transfers
    events = await check_torn_events(torn_api_key)
    if events is None:
        return 0, 0
    
    # Check each pending order
    verified_orders = []
    still_pending = []

    # Get current time for 24-hour lookback limit
    current_time = datetime.now()
    lookback_limit = current_time - timedelta(hours=24)
    
    for order_id, order_data in pending_order.items():
        coverage_type = order_data.get('coverage_type', 'XAN')
        message_code = 'HJSx' if coverage_type == 'XAN' else 'HJSe'
        username = order_data.get('username', 'Unknown')
        display_name = order_data.get('display_name', username)
        
        # Expected payment amount
        expected_payment = order_data.get('xanax_payment', 0)
        
        # Extract clean name for matching (remove [ID] part)
        display_name_clean = display_name.split('[')[0].strip() if '[' in display_name else display_name
        
        # Search for matching payment in log entries
        payment_found = False
        matching_event = None
        
        # Handle different log entry formats
        log_items = []
        if isinstance(events, dict):
            log_items = events.items()
        elif isinstance(events, list):
            log_items = [(i, entry) for i, entry in enumerate(events)]
        
        processed_entries = 0
        for log_id, log_entry in log_items:
            if not isinstance(log_entry, dict):
                continue
                
            processed_entries += 1
            log_text = log_entry.get('log', '')
            # For events API, the main content is in 'event' field, not 'log'
            event_text = log_entry.get('event', '')
            
            # Use event text if log text is empty (which it usually is with events API)
            if event_text and not log_text:
                log_text = event_text
            
            # Ensure log_text is always a string
            if not isinstance(log_text, str):
                log_text = str(log_text)
            log_text_lower = log_text.lower()
            log_category = log_entry.get('category', '')
            log_timestamp = log_entry.get('timestamp', 0)
            log_time = datetime.fromtimestamp(log_timestamp)
            
            # Skip entries older than 24 hours
            if log_time < lookback_limit:
                continue
            
            # Only check logs that might be relevant (contain xanax or message codes)
            contains_xanax = 'xanax' in log_text_lower
            contains_message_code = message_code.lower() in log_text_lower
            contains_hjsx = 'hjsx' in log_text_lower
            contains_hjse = 'hjse' in log_text_lower
            
            # ALSO check if any other fields contain these keywords
            other_fields_match = False
            for key, value in log_entry.items():
                if isinstance(value, str):
                    value_lower = value.lower()
                    if ('xanax' in value_lower or 'hjsx' in value_lower or 'hjse' in value_lower or message_code.lower() in value_lower):
                        other_fields_match = True
                        break
            
            if not (contains_xanax or contains_hjsx or contains_hjse or contains_message_code or other_fields_match):
                continue
                
            # Look for item transfers mentioning Xanax (FIXED DETECTION)
            has_xanax = 'xanax' in log_text_lower
            has_message_code = message_code.lower() in log_text_lower
            # Fix transfer detection - handle both "You were sent" and "sent...to you" formats
            has_transfer = (('sent' in log_text_lower and 'to you' in log_text_lower) or 
                          'you were sent' in log_text_lower or 
                          'received' in log_text_lower)
            
            if has_xanax and has_message_code and has_transfer:
                
                # Verify payment amount - handle both "some Xanax" and "Zx Xanax" formats
                payment_amount_found = False
                
                # First try to find "Zx Xanax" pattern
                xanax_pattern = re.search(r'(\d+)x?\s*xanax', log_text_lower)
                if xanax_pattern:
                    found_amount = int(xanax_pattern.group(1))
                    if found_amount == expected_payment:
                        payment_amount_found = True
                elif 'some xanax' in log_text_lower and expected_payment == 1:
                    payment_amount_found = True  # "some" means 1
                else:
                    # Fallback: look for any numbers in the text
                    numbers_in_text = re.findall(r'\d+', log_text)
                    for num_str in numbers_in_text:
                        if int(num_str) == expected_payment:
                            payment_amount_found = True
                            break
                
                # Verify username/nickname appears in the log - IMPROVED LOGIC
                # (display_name_clean already defined earlier)
                
                display_name_found = display_name_clean.lower() in log_text_lower
                username_found = username.lower() in log_text_lower
                
                # Also check for partial matches and common variations
                display_name_words = display_name_clean.lower().split()
                username_words = username.lower().split()
                
                partial_display_match = any(word in log_text_lower for word in display_name_words if len(word) > 2)
                partial_username_match = any(word in log_text_lower for word in username_words if len(word) > 2)
                
                name_match_found = display_name_found or username_found or partial_display_match or partial_username_match
                
                # Additional validation - check if it's within 1 hour of order time (before or after)
                order_time = datetime.strptime(order_data.get('timestamp'), '%Y-%m-%d %H:%M:%S')
                time_difference = abs((log_time - order_time).total_seconds())
                time_valid = time_difference <= 3600  # Allow 1 hour before or after
                
                # If payment was made before order, update the order timestamp to payment time
                payment_made_first = log_time < order_time
                
                if (time_valid and payment_amount_found and name_match_found):
                    payment_found = True
                    
                    # Use the actual payment timestamp if it was made before the order
                    final_timestamp = log_time if payment_made_first else order_time
                    
                    matching_event = {
                        'log': log_entry.get('log', ''),
                        'event_text': event_text,  # Store the full event text
                        'timestamp': log_time,
                        'log_id': log_id,
                        'category': log_category,
                        'verified_amount': expected_payment,
                        'verified_user': True,
                        'matched_name': display_name_clean if display_name_found else username,
                        'payment_made_first': payment_made_first
                    }
                    # Update order timestamp to when payment was actually received
                    order_data['payment_received_at'] = log_time.strftime('%Y-%m-%d %H:%M:%S')
                    if payment_made_first:
                        order_data['timestamp'] = log_time.strftime('%Y-%m-%d %H:%M:%S')  # Update order time to payment time
                    break
        
        if payment_found:
            verified_orders.append({
                'order_id': order_id,
                'order_data': order_data,
                'payment_event': matching_event,
                'message_code': message_code
            })
        else:
            still_pending.append({
                'order_id': order_id,
                'order_data': order_data,
                'message_code': message_code
            })
    
    # Activate verified orders
    activated_count = 0
    for order in verified_orders:
        order_id = order['order_id']
        order_data = order['order_data']
        
        # Move to active orders
        active_orders[order_id] = order_data.copy()
        activation_time = datetime.now()
        active_orders[order_id]['activated_at'] = activation_time.strftime('%Y-%m-%d %H:%M:%S')
        
        # Calculate and set expiration time
        coverage_type = order_data.get('coverage_type', 'XAN')
        if coverage_type == 'XAN':
            hours = order_data.get('hours', 24)
            expiry_time = activation_time + timedelta(hours=hours)
        else:  # EXTC
            expiry_time = activation_time + timedelta(hours=2)  # EXTC coverage is always 2 hours
        
        active_orders[order_id]['expires_at'] = expiry_time.strftime('%Y-%m-%d %H:%M:%S')
        
        # Update database
        db.activate_coverage(order_id, activation_time)
        
        # Remove from pending
        if order_id in pending_order:
            del pending_order[order_id]
        
        activated_count += 1
        
        # Send thank you message and review request
        user_id = order_data.get('user_id')
        if user_id:
            user = guild.get_member(user_id)
            if user:
                thank_you_embed = discord.Embed(
                    title="🙏 Thank You for Your Order!",
                    description="Your insurance coverage has been activated. We appreciate your business!",
                    color=discord.Color.gold()
                )
                thank_you_embed.add_field(
                    name="📝 Leave a Review",
                    value="We'd love to hear your feedback! Please consider leaving a review:",
                    inline=False
                )
                thank_you_embed.add_field(
                    name="🌐 Torn Forums",
                    value="[Click here to leave a review on Torn Forums](https://www.torn.com/forums.php#/p=threads&f=10&t=16512240&b=0&a=0&start=0&to=26576367)",
                    inline=False
                )
                thank_you_embed.add_field(
                    name="💬 Discord Reviews",
                    value="Please share your experience in our <#review> channel!",
                    inline=False
                )
                try:
                    await user.send(embed=thank_you_embed)
                except:
                    pass  # User might have DMs disabled
        
        # Update user's original message to show accepted status
        user_message = order_data.get('user_message')
        if user_message:
            try:
                # Create updated embed
                coverage_type = order_data.get('coverage_type', 'XAN')
                
                if coverage_type == 'XAN':
                    hours = order_data.get('hours', 24)
                    xanax_payment = order_data.get('xanax_payment', 0)
                    xanax_reward = order_data.get('xanax_reward', 0)
                    
                    updated_embed = discord.Embed(
                        title="🔒 Xanax Insurance Order",
                        description=f"**Coverage Duration:** {hours} hours\n**Payment Required:** {xanax_payment} Xanax",
                        color=discord.Color.green()
                    )
                    updated_embed.add_field(
                        name="💊 Payment Instructions",
                        value=f"Send **{xanax_payment} Xanax** to [Danieltrsl](https://www.torn.com/profiles.php?XID=2823859)\n⚠️ **Include message: HJSx** - Payments without this message will be voided!",
                        inline=False
                    )
                    updated_embed.add_field(
                        name="🎁 In the Event of Overdose",
                        value=f"You will be rewarded **{xanax_reward} Xanax**",
                        inline=False
                    )
                    
                    # Calculate expiry time
                    expiry_time = datetime.strptime(active_orders[order_id]['expires_at'], '%Y-%m-%d %H:%M:%S')
                    time_remaining = expiry_time - datetime.now()
                    hours_remaining = int(time_remaining.total_seconds() // 3600)
                    minutes_remaining = int((time_remaining.total_seconds() % 3600) // 60)
                    
                    updated_embed.add_field(
                        name="📋 Order Details",
                        value=f"**User:** <@{order_data['user_id']}>\n**Date/Time:** {activation_time.strftime('%m/%d %H:%M')}\n**Status:** ✅ Accepted",
                        inline=False
                    )
                    updated_embed.add_field(
                        name="⏰ Coverage Active",
                        value=f"**Time Remaining:** {hours_remaining}h {minutes_remaining}m\n**Expires:** <t:{int(expiry_time.timestamp())}:f>",
                        inline=False
                    )
                    updated_embed.set_footer(text="Your insurance is now ACTIVE!")
                
                else:  # EXTC
                    jumps = order_data.get('jumps', 1)
                    xanax_payment = order_data.get('xanax_payment', 0)
                    edvds_reward = order_data.get('edvds_reward', 0)
                    xanax_reward = order_data.get('xanax_reward', 0)
                    ecstasy_reward = order_data.get('ecstasy_reward', 0)
                    
                    updated_embed = discord.Embed(
                        title="💊 Ecstasy Insurance Order",
                        description=f"**Coverage:** {jumps} Jump{'s' if jumps > 1 else ''}\n**Payment Required:** {xanax_payment} Xanax",
                        color=discord.Color.green()
                    )
                    updated_embed.add_field(
                        name="💰 Payment Instructions",
                        value=f"Send **{xanax_payment} Xanax** to [Danieltrsl](https://www.torn.com/profiles.php?XID=2823859)\n⚠️ **Include message: HJSe** - Payments without this message will be voided!",
                        inline=False
                    )
                    updated_embed.add_field(
                        name="🎁 In the Event of Overdose",
                        value=f"You will be rewarded:\n• **{edvds_reward} eDVDs**\n• **{xanax_reward} Xanax**\n• **{ecstasy_reward} Ecstasy**",
                        inline=False
                    )
                    
                    # Calculate expiry time (EXTC is 2 hours)
                    expiry_time = datetime.strptime(active_orders[order_id]['expires_at'], '%Y-%m-%d %H:%M:%S')
                    time_remaining = expiry_time - datetime.now()
                    hours_remaining = int(time_remaining.total_seconds() // 3600)
                    minutes_remaining = int((time_remaining.total_seconds() % 3600) // 60)
                    
                    updated_embed.add_field(
                        name="📋 Order Details",
                        value=f"**User:** <@{order_data['user_id']}>\n**Date/Time:** {activation_time.strftime('%m/%d %H:%M')}\n**Status:** ✅ Accepted",
                        inline=False
                    )
                    updated_embed.add_field(
                        name="⏰ Coverage Active",
                        value=f"**Time Remaining:** {hours_remaining}h {minutes_remaining}m\n**Expires:** <t:{int(expiry_time.timestamp())}:f>",
                        inline=False
                    )
                    updated_embed.set_footer(text="Your insurance is now ACTIVE!")
                
                # Update the original message
                await user_message.edit(embed=updated_embed)
            except Exception as e:
                print(f"Error updating user message: {e}")
        
        # Log activation to order channel
        order_channel = discord.utils.get(guild.channels, name="order")
        if order_channel:
            display_name = order_data.get('display_name', order_data.get('username', 'Unknown'))
            coverage_type = order_data.get('coverage_type', 'XAN')
            auto_detected = order_data.get('auto_detected', False)
            
            embed = discord.Embed(
                title="✅ Insurance Activated",
                description=f"**{display_name}** insurance is now active",
                color=discord.Color.green()
            )
            
            if coverage_type == 'XAN':
                hours = order_data.get('hours', 24)
                reward = order_data.get('xanax_reward', 0)
                embed.add_field(
                    name="Coverage Details",
                    value=f"**Type:** Xanax Overdose\n**Duration:** {hours} hours\n**Payout:** {reward} Xanax",
                    inline=False
                )
            else:
                jumps = order_data.get('jumps', 1)
                edvds_reward = order_data.get('edvds_reward', 0)
                xanax_reward = order_data.get('xanax_reward', 0)
                ecstasy_reward = order_data.get('ecstasy_reward', 0)
                embed.add_field(
                    name="Coverage Details",
                    value=f"**Type:** Ecstasy Overdose\n**Jumps:** {jumps}\n**Payout:** {edvds_reward} eDVDs, {xanax_reward} Xanax, {ecstasy_reward} Ecstasy",
                    inline=False
                )
            
            status_text = "Payment verified" + (" (auto-detected)" if auto_detected else "")
            embed.add_field(name="Status", value=status_text, inline=False)
            embed.set_footer(text=f"Activated: {datetime.now().strftime('%m/%d %H:%M')}")
            
            try:
                await order_channel.send(embed=embed)
            except:
                pass
    
    return len(still_pending), activated_count

@bot.tree.command(name="order", description="Check all pending orders against Torn API events (Admin only)")
async def check_order(interaction: discord.Interaction):
    """Check all pending orders for payment confirmation via Torn API"""
    
    # Admin only check
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can check pending orders.", ephemeral=True)
        return
    
    # Get API key from environment
    torn_api_key = get_api_key()
    if not torn_api_key:
        await interaction.response.send_message("❌ Torn API key not configured! Use /apikeyadd to set it.", ephemeral=True)
        return
    
    # Check if there are pending orders
    if not pending_order:
        await interaction.response.send_message("📋 No pending orders to check.", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    # Use the shared order checking function
    still_pending_count, activated_count = await perform_order_check(interaction.guild, torn_api_key)
    
    # Create response embed
    embed = discord.Embed(
        title="📋 Order Payment Check Results",
        description=f"Manual order check completed",
        color=discord.Color.blue()
    )
    
    if activated_count > 0:
        embed.add_field(
            name=f"✅ Verified and Activated ({activated_count})",
            value=f"{activated_count} order(s) were verified and activated automatically.",
            inline=False
        )
    
    if still_pending_count > 0:
        embed.add_field(
            name=f"⏳ Still Pending ({still_pending_count})",
            value=f"{still_pending_count} order(s) are still awaiting payment confirmation.",
            inline=False
        )
    
    if activated_count == 0 and still_pending_count == 0:
        embed.add_field(
            name="📝 Status",
            value="No pending orders found to process.",
            inline=False
        )
    
    # Add instructions
    if activated_count > 0:
        embed.add_field(
            name="📋 Next Steps",
            value="✅ Verified orders have been automatically activated and moved to active insurance!",
            inline=False
        )
    
    embed.set_footer(text=f"Requested by: {interaction.user.display_name}")
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="activate", description="Manually activate a verified order (Admin only)")
@app_commands.describe(user="Discord user whose order to activate")
async def activate_order(interaction: discord.Interaction, user: discord.Member):
    """Manually activate a verified order"""
    
    # Admin only check
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can activate orders.", ephemeral=True)
        return
    
    # Find user's pending order
    user_orders = [(order_id, data) for order_id, data in pending_order.items() if data.get('user_id') == user.id]
    
    if not user_orders:
        await interaction.response.send_message(f"❌ No pending orders found for {user.mention}.", ephemeral=True)
        return
    
    if len(user_orders) > 1:
        await interaction.response.send_message(f"❌ Multiple orders found for {user.mention}. Please resolve manually.", ephemeral=True)
        return
    
    order_id, order_data = user_orders[0]
    
    # Use payment received time if available, otherwise current time
    payment_received_at = order_data.get('payment_received_at')
    if payment_received_at:
        activation_time = datetime.strptime(payment_received_at, '%Y-%m-%d %H:%M:%S')
    else:
        activation_time = datetime.now()
    
    coverage_type = order_data.get('coverage_type', 'XAN')
    
    # Calculate expiry time based on when payment was received
    if coverage_type == 'XAN':
        hours = order_data.get('hours', 24)
        expiry_time = activation_time + timedelta(hours=hours)
    else:  # EXTC
        expiry_time = activation_time + timedelta(hours=2)  # EXTC coverage is always 2 hours
    
    # Move to active orders
    active_orders[order_id] = {
        **order_data,
        'activated_at': activation_time.strftime('%Y-%m-%d %H:%M:%S'),
        'expires_at': expiry_time.strftime('%Y-%m-%d %H:%M:%S'),
        'status': 'active'
    }
    
    # Remove from pending
    del pending_order[order_id]
    
    # Update user's original message to show accepted status
    user_message = order_data.get('user_message')
    if user_message:
        try:
            # Create updated embed similar to the auto-check update
            if coverage_type == 'XAN':
                hours = order_data.get('hours', 24)
                xanax_payment = order_data.get('xanax_payment', 0)
                xanax_reward = order_data.get('xanax_reward', 0)
                
                updated_embed = discord.Embed(
                    title="🔒 Xanax Insurance Order",
                    description=f"**Coverage Duration:** {hours} hours\n**Payment Required:** {xanax_payment} Xanax",
                    color=discord.Color.green()
                )
                updated_embed.add_field(
                    name="💊 Payment Instructions",
                    value=f"Send **{xanax_payment} Xanax** to [Danieltrsl](https://www.torn.com/profiles.php?XID=2823859)\n⚠️ **Include message: HJSx** - Payments without this message will be voided!",
                    inline=False
                )
                updated_embed.add_field(
                    name="🎁 In the Event of Overdose",
                    value=f"You will be rewarded **{xanax_reward} Xanax**",
                    inline=False
                )
                
                # Calculate time remaining
                time_remaining = expiry_time - activation_time
                hours_remaining = int(time_remaining.total_seconds() // 3600)
                minutes_remaining = int((time_remaining.total_seconds() % 3600) // 60)
                
                updated_embed.add_field(
                    name="📋 Order Details",
                    value=f"**User:** <@{order_data['user_id']}>\n**Date/Time:** {activation_time.strftime('%m/%d %H:%M')}\n**Status:** ✅ Accepted",
                    inline=False
                )
                updated_embed.add_field(
                    name="⏰ Coverage Active",
                    value=f"**Time Remaining:** {hours_remaining}h {minutes_remaining}m\n**Expires:** <t:{int(expiry_time.timestamp())}:f>",
                    inline=False
                )
                updated_embed.set_footer(text="Your insurance is now ACTIVE!")
            
            else:  # EXTC
                jumps = order_data.get('jumps', 1)
                xanax_payment = order_data.get('xanax_payment', 0)
                edvds_reward = order_data.get('edvds_reward', 0)
                xanax_reward = order_data.get('xanax_reward', 0)
                ecstasy_reward = order_data.get('ecstasy_reward', 0)
                
                updated_embed = discord.Embed(
                    title="💊 Ecstasy Insurance Order",
                    description=f"**Coverage:** {jumps} Jump{'s' if jumps > 1 else ''}\n**Payment Required:** {xanax_payment} Xanax",
                    color=discord.Color.green()
                )
                updated_embed.add_field(
                    name="💰 Payment Instructions",
                    value=f"Send **{xanax_payment} Xanax** to [Danieltrsl](https://www.torn.com/profiles.php?XID=2823859)\n⚠️ **Include message: HJSe** - Payments without this message will be voided!",
                    inline=False
                )
                updated_embed.add_field(
                    name="🎁 In the Event of Overdose",
                    value=f"You will be rewarded:\n• **{edvds_reward} eDVDs**\n• **{xanax_reward} Xanax**\n• **{ecstasy_reward} Ecstasy**",
                    inline=False
                )
                
                # Calculate time remaining (EXTC is 2 hours)
                time_remaining = expiry_time - activation_time
                hours_remaining = int(time_remaining.total_seconds() // 3600)
                minutes_remaining = int((time_remaining.total_seconds() % 3600) // 60)
                
                updated_embed.add_field(
                    name="📋 Order Details",
                    value=f"**User:** <@{order_data['user_id']}>\n**Date/Time:** {activation_time.strftime('%m/%d %H:%M')}\n**Status:** ✅ Accepted",
                    inline=False
                )
                updated_embed.add_field(
                    name="⏰ Coverage Active",
                    value=f"**Time Remaining:** {hours_remaining}h {minutes_remaining}m\n**Expires:** <t:{int(expiry_time.timestamp())}:f>",
                    inline=False
                )
                updated_embed.set_footer(text="Your insurance is now ACTIVE!")
            
            # Update the original message
            await user_message.edit(embed=updated_embed)
        except Exception as e:
            print(f"Error updating user message in manual activation: {e}")
    
    # Create response
    embed = discord.Embed(
        title="✅ Order Activated",
        description=f"Order for {user.mention} has been activated!",
        color=discord.Color.green()
    )
    
    if coverage_type == 'XAN':
        hours = order_data.get('hours', 24)
        payment_note = f"\n**Payment received:** {activation_time.strftime('%m/%d %H:%M')}" if payment_received_at else ""
        embed.add_field(
            name="Coverage Details",
            value=f"**Type:** Xanax Insurance\n**Duration:** {hours} hours{payment_note}\n**Coverage active until:** {expiry_time.strftime('%m/%d %H:%M')}",
            inline=False
        )
    else:
        jumps = order_data.get('jumps', 1)
        payment_note = f"\n**Payment received:** {activation_time.strftime('%m/%d %H:%M')}" if payment_received_at else ""
        embed.add_field(
            name="Coverage Details", 
            value=f"**Type:** Ecstasy Insurance\n**Coverage:** {jumps} Jump{'s' if jumps > 1 else ''}\n**Duration:** 2 hours{payment_note}\n**Coverage active until:** {expiry_time.strftime('%m/%d %H:%M')}",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="active", description="View currently active insurance orders (Admin only)")
async def active_orders_command(interaction: discord.Interaction):
    """View currently active insurance orders"""
    
    # Admin only check
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can view active orders.", ephemeral=True)
        return
    
    current_time = datetime.now()
    active_list = []
    expired_list = []
    
    # Check each active order
    for order_id, order_data in active_orders.items():
        # Handle missing expires_at field (from old orders)
        expires_at_str = order_data.get('expires_at')
        activated_at_str = order_data.get('activated_at')
        
        if not expires_at_str or not activated_at_str:
            # Skip orders with missing timestamps (old orders)
            continue
            
        try:
            expires_at = datetime.strptime(expires_at_str, '%Y-%m-%d %H:%M:%S')
            activated_at = datetime.strptime(activated_at_str, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            # Skip orders with invalid timestamps
            continue
        
        if current_time < expires_at:
            # Still active
            time_remaining = expires_at - current_time
            hours_remaining = int(time_remaining.total_seconds() // 3600)
            minutes_remaining = int((time_remaining.total_seconds() % 3600) // 60)
            
            active_list.append({
                'order_data': order_data,
                'activated_time': activated_at.strftime('%H:%M'),
                'expires_time': expires_at.strftime('%H:%M'),
                'time_remaining': f"{hours_remaining}h {minutes_remaining}m"
            })
    
    embed = discord.Embed(
        title="🛡️ Active Insurance Orders",
        description=f"Currently tracking {len(active_list)} active order(s)",
        color=discord.Color.green()
    )
    
    if active_list:
        for i, order in enumerate(active_list[:10], 1):  # Show max 10
            data = order['order_data']
            coverage_type = data.get('coverage_type', 'XAN')
            username = data.get('username', 'Unknown')
            
            if coverage_type == 'XAN':
                hours = data.get('hours', 24)
                coverage_info = f"{hours}H Xanax coverage"
            else:
                jumps = data.get('jumps', 1)
                coverage_info = f"{jumps} Jump Ecstasy coverage (2H)"
            
            embed.add_field(
                name=f"#{i} {username}",
                value=f"**Coverage:** {coverage_info}\n**Active since:** {order['activated_time']}\n**Expires:** {order['expires_time']}\n**Time left:** {order['time_remaining']}",
                inline=True
            )
    else:
        embed.add_field(
            name="📋 No Active Orders",
            value="No insurance orders are currently active.",
            inline=False
        )
    
    embed.set_footer(text=f"Requested by: {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="expired", description="View expired insurance orders (Admin only)")
async def expired_orders_command(interaction: discord.Interaction):
    """View expired insurance orders"""
    
    # Admin only check
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can view expired orders.", ephemeral=True)
        return
    
    current_time = datetime.now()
    expired_list = []
    
    # Check each active order for expiry
    orders_to_remove = []
    for order_id, order_data in active_orders.items():
        # Handle missing expires_at field (from old orders)
        expires_at_str = order_data.get('expires_at')
        activated_at_str = order_data.get('activated_at')
        
        if not expires_at_str or not activated_at_str:
            # Mark old orders without timestamps for removal
            orders_to_remove.append(order_id)
            continue
            
        try:
            expires_at = datetime.strptime(expires_at_str, '%Y-%m-%d %H:%M:%S')
            activated_at = datetime.strptime(activated_at_str, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            # Mark orders with invalid timestamps for removal
            orders_to_remove.append(order_id)
            continue
        
        if current_time >= expires_at:
            # Expired
            time_since_expired = current_time - expires_at
            hours_expired = int(time_since_expired.total_seconds() // 3600)
            minutes_expired = int((time_since_expired.total_seconds() % 3600) // 60)
            
            expired_list.append({
                'order_data': order_data,
                'activated_time': activated_at.strftime('%H:%M'),
                'expired_time': expires_at.strftime('%H:%M'),
                'time_since_expired': f"{hours_expired}h {minutes_expired}m ago"
            })
            
            orders_to_remove.append(order_id)
    
    # Remove expired orders from active list
    for order_id in orders_to_remove:
        del active_orders[order_id]
    
    embed = discord.Embed(
        title="⏰ Expired Insurance Orders",
        description=f"Found {len(expired_list)} expired order(s)",
        color=discord.Color.red()
    )
    
    if expired_list:
        for i, order in enumerate(expired_list[:10], 1):  # Show max 10
            data = order['order_data']
            coverage_type = data.get('coverage_type', 'XAN')
            username = data.get('username', 'Unknown')
            
            if coverage_type == 'XAN':
                hours = data.get('hours', 24)
                coverage_info = f"{hours}H Xanax coverage"
            else:
                jumps = data.get('jumps', 1)
                coverage_info = f"{jumps} Jump Ecstasy coverage (2H)"
            
            embed.add_field(
                name=f"#{i} {username}",
                value=f"**Coverage:** {coverage_info}\n**Was active:** {order['activated_time']} - {order['expired_time']}\n**Expired:** {order['time_since_expired']}",
                inline=True
            )
        
        embed.add_field(
            name="🗑️ Cleanup",
            value="Expired orders have been automatically removed from active list.",
            inline=False
        )
    else:
        embed.add_field(
            name="📋 No Expired Orders",
            value="No expired orders found at this time.",
            inline=False
        )
    
    embed.set_footer(text=f"Requested by: {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="check", description="Check your current insurance status")
async def check_insurance(interaction: discord.Interaction):
    """Check if user has active insurance coverage"""
    
    user = interaction.user
    current_time = datetime.now()
    
    # Check for active insurance
    user_active_orders = []
    user_pending_orders = []
    
    # Look through active orders
    for order_id, order_data in active_orders.items():
        if order_data.get('user_id') == user.id:
            # Get expiration time from stored data or calculate it
            expires_at_str = order_data.get('expires_at')
            if expires_at_str:
                try:
                    expiry_time = datetime.strptime(expires_at_str, '%Y-%m-%d %H:%M:%S')
                except (ValueError, TypeError):
                    # If invalid, calculate from activation and coverage type
                    activation_time = datetime.strptime(order_data.get('activated_at'), '%Y-%m-%d %H:%M:%S')
                    coverage_type = order_data.get('coverage_type', 'XAN')
                    if coverage_type == 'XAN':
                        hours = order_data.get('hours', 24)
                        expiry_time = activation_time + timedelta(hours=hours)
                    else:  # EXTC
                        expiry_time = activation_time + timedelta(hours=2)
            else:
                # Calculate from activation and coverage type for old orders
                activation_time = datetime.strptime(order_data.get('activated_at'), '%Y-%m-%d %H:%M:%S')
                coverage_type = order_data.get('coverage_type', 'XAN')
                if coverage_type == 'XAN':
                    hours = order_data.get('hours', 24)
                    expiry_time = activation_time + timedelta(hours=hours)
                else:  # EXTC
                    expiry_time = activation_time + timedelta(hours=2)
            
            if current_time < expiry_time:
                activation_time = datetime.strptime(order_data.get('activated_at'), '%Y-%m-%d %H:%M:%S')
                coverage_type = order_data.get('coverage_type', 'Unknown')
                time_left = expiry_time - current_time
                hours_left = int(time_left.total_seconds() // 3600)
                minutes_left = int((time_left.total_seconds() % 3600) // 60)
                
                user_active_orders.append({
                    'type': coverage_type,
                    'expires_at': expiry_time,
                    'time_left': f"{hours_left}h {minutes_left}m",
                    'activated_at': activation_time
                })
    
    # Look through pending orders
    for order_id, order_data in pending_order.items():
        if order_data.get('user_id') == user.id:
            coverage_type = order_data.get('coverage_type', 'Unknown')
            order_time = datetime.strptime(order_data.get('timestamp'), '%Y-%m-%d %H:%M:%S')
            
            user_pending_orders.append({
                'type': coverage_type,
                'ordered_at': order_time,
                'payment_required': order_data.get('xanax_payment', 0),
                'message_code': 'HJSx' if coverage_type == 'XAN' else 'HJSe'
            })
    
    # Create response embed
    if user_active_orders or user_pending_orders:
        embed = discord.Embed(
            title="📋 Your Insurance Status",
            description=f"Insurance status for {user.display_name}",
            color=discord.Color.blue()
        )
        
        # Show active coverage
        if user_active_orders:
            active_text = ""
            for order in user_active_orders:
                coverage_emoji = "💊" if order['type'] == 'XAN' else "🌟"
                active_text += f"{coverage_emoji} **{order['type']} Coverage**\n"
                active_text += f"   └ Expires in: {order['time_left']}\n"
                active_text += f"   └ Activated: {order['activated_at'].strftime('%m/%d %H:%M')}\n\n"
            
            embed.add_field(
                name="✅ Active Coverage",
                value=active_text.strip(),
                inline=False
            )
        
        # Show pending orders
        if user_pending_orders:
            pending_text = ""
            for order in user_pending_orders:
                coverage_emoji = "💊" if order['type'] == 'XAN' else "🌟"
                pending_text += f"{coverage_emoji} **{order['type']} Order**\n"
                pending_text += f"   └ Payment needed: {order['payment_required']} Xanax\n"
                pending_text += f"   └ Message code: `{order['message_code']}`\n"
                pending_text += f"   └ Ordered: {order['ordered_at'].strftime('%m/%d %H:%M')}\n\n"
            
            embed.add_field(
                name="⏳ Pending Orders",
                value=pending_text.strip(),
                inline=False
            )
            
            embed.add_field(
                name="💡 Next Steps",
                value="Send the required Xanax payment with the message code to activate your insurance.",
                inline=False
            )
    else:
        embed = discord.Embed(
            title="📋 Your Insurance Status",
            description=f"{user.display_name}, you currently have no active or pending insurance.",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="💡 Get Insured",
            value="Use `/xan` for Xanax overdose coverage or `/extc` for Ecstasy overdose coverage.",
            inline=False
        )
    
    embed.set_footer(text=f"Checked at: {current_time.strftime('%m/%d/%Y %H:%M')}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="od", description="Report an overdose for insurance payout")
async def report_overdose(interaction: discord.Interaction):
    """Report an overdose for insurance payout"""
    
    user = interaction.user
    guild = interaction.guild
    
    # Check if user has active coverage
    user_active_orders = [(order_id, data) for order_id, data in active_orders.items() if data.get('user_id') == user.id]
    
    if not user_active_orders:
        await interaction.response.send_message("❌ You don't have any active insurance coverage to claim against.", ephemeral=True)
        return
    
    if len(user_active_orders) > 1:
        await interaction.response.send_message("❌ You have multiple active orders. Please contact an administrator for manual processing.", ephemeral=True)
        return
    
    order_id, order_data = user_active_orders[0]
    
    # Check if user already has a pending overdose report
    existing_reports = [report for report in overdose_reports.values() if report.get('user_id') == user.id and report.get('status') == 'pending']
    if existing_reports:
        await interaction.response.send_message("❌ You already have a pending overdose report. Please wait for admin review.", ephemeral=True)
        return
    
    # Create overdose report
    report_time = datetime.now()
    report_id = f"{user.id}_{report_time.timestamp()}"
    
    coverage_type = order_data.get('coverage_type', 'XAN')
    
    # Calculate payout
    if coverage_type == 'XAN':
        xanax_reward = order_data.get('xanax_reward', 0)
        payout_details = f"{xanax_reward} Xanax"
    else:  # EXTC
        edvds_reward = order_data.get('edvds_reward', 0)
        xanax_reward = order_data.get('xanax_reward', 0)
        ecstasy_reward = order_data.get('ecstasy_reward', 0)
        payout_details = f"{edvds_reward} eDVDs, {xanax_reward} Xanax, {ecstasy_reward} Ecstasy"
    
    # Store overdose report
    overdose_reports[report_id] = {
        'user_id': user.id,
        'username': str(user),
        'order_id': order_id,
        'order_data': order_data,
        'coverage_type': coverage_type,
        'payout_details': payout_details,
        'reported_at': report_time.strftime('%Y-%m-%d %H:%M:%S'),
        'status': 'pending'
    }
    
    # Send confirmation to user
    embed = discord.Embed(
        title="🚨 Overdose Report Submitted",
        description="Your overdose has been reported and is pending admin verification.",
        color=discord.Color.yellow()
    )
    embed.add_field(
        name="📋 Report Details",
        value=f"**Coverage Type:** {coverage_type}\n**Expected Payout:** {payout_details}\n**Reported:** {report_time.strftime('%m/%d %H:%M')}\n**Status:** Pending Review",
        inline=False
    )
    embed.add_field(
        name="⏳ Next Steps",
        value="An administrator will verify your overdose and process the payout. Please wait for confirmation.",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    
    # Send to order channel
    order_channel = discord.utils.get(guild.channels, name="order")
    if order_channel:
        log_embed = discord.Embed(
            title="🚨 New Overdose Report",
            description=f"{user.mention} reported an overdose at **{report_time.strftime('%m/%d %H:%M')}**",
            color=discord.Color.red()
        )
        log_embed.add_field(
            name="Details",
            value=f"**Coverage:** {coverage_type}\n**Expected Payout:** {payout_details}\n**Status:** Pending Verification",
            inline=False
        )
        log_embed.set_footer(text=f"Report ID: {report_id} | User ID: {user.id}")
        await order_channel.send(embed=log_embed)

@bot.tree.command(name="odfin", description="Finalize an overdose payout (Admin only)")
@app_commands.describe(user="User whose overdose report to finalize")
async def finalize_overdose(interaction: discord.Interaction, user: discord.Member):
    """Finalize an overdose payout (Admin only)"""
    
    # Check if user is admin
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can finalize overdose payouts.", ephemeral=True)
        return
    
    # Find user's pending overdose report
    user_reports = [(report_id, data) for report_id, data in overdose_reports.items() 
                   if data.get('user_id') == user.id and data.get('status') == 'pending']
    
    if not user_reports:
        await interaction.response.send_message(f"❌ No pending overdose reports found for {user.mention}.", ephemeral=True)
        return
    
    if len(user_reports) > 1:
        await interaction.response.send_message(f"❌ Multiple pending reports found for {user.mention}. Please resolve manually.", ephemeral=True)
        return
    
    report_id, report_data = user_reports[0]
    
    # Mark report as finalized
    overdose_reports[report_id]['status'] = 'finalized'
    overdose_reports[report_id]['finalized_by'] = str(interaction.user)
    overdose_reports[report_id]['finalized_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Record payout in database
    coverage_type = report_data.get('coverage_type', 'XAN')
    if coverage_type == 'XAN':
        xanax_amount = report_data.get('order_data', {}).get('xanax_reward', 0)
    else:  # EXTC
        xanax_amount = report_data.get('order_data', {}).get('xanax_reward', 0)
    
    if xanax_amount > 0:
        db.record_payout(
            report_data.get('order_id'),
            user.id,
            str(user),
            xanax_amount,
            f"Overdose payout - {coverage_type}"
        )
    
    # Keep the active order (coverage remains active)
    order_id = report_data.get('order_id')
    
    # Create confirmation embed
    embed = discord.Embed(
        title="✅ Overdose Payout Finalized",
        description=f"Overdose report for {user.mention} has been approved and finalized.",
        color=discord.Color.green()
    )
    embed.add_field(
        name="💰 Payout Details",
        value=f"**User:** {user.mention}\n**Coverage:** {report_data.get('coverage_type')}\n**Payout:** {report_data.get('payout_details')}",
        inline=False
    )
    embed.add_field(
        name="📋 Action Required",
        value=f"Send **{report_data.get('payout_details')}** to {user.mention}\nInsurance coverage remains active.",
        inline=False
    )
    embed.set_footer(text=f"Finalized by: {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed)
    
    # Update payout channel
    payout_channel = discord.utils.get(interaction.guild.channels, name="payout")
    if payout_channel:
        log_embed = discord.Embed(
            title="✅ Overdose Payout Approved",
            description=f"**{user.mention}**'s overdose has been verified and approved for payout.",
            color=discord.Color.green()
        )
        log_embed.add_field(
            name="Final Details",
            value=f"**Payout:** {report_data.get('payout_details')}\n**Finalized by:** {interaction.user.mention}\n**Time:** {datetime.now().strftime('%m/%d %H:%M')}",
            inline=False
        )
        log_embed.set_footer(text=f"Report ID: {report_id}")
        await payout_channel.send(embed=log_embed)

@bot.tree.command(name="givecover", description="Give a user drug-specific coverage (Admin only)")
@app_commands.describe(
    user="User to give coverage to",
    drug_type="Type of drug coverage to give",
    duration="Duration in hours for Xanax cover, or number of jumps for Ecstasy",
    reward="Amount of reward for coverage"
)
@app_commands.choices(drug_type=[
    app_commands.Choice(name="Xanax", value="XAN"),
    app_commands.Choice(name="Ecstasy", value="EXTC")
])
async def give_coverage(interaction: discord.Interaction, user: discord.Member, drug_type: app_commands.Choice[str], duration: int, reward: int):
    """Give a user drug-specific coverage (Admin only)"""
    
    # Check if user is admin
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can give coverage.", ephemeral=True)
        return
    
    # Create a new active order
    order_time = datetime.now()
    order_id = f"{user.id}_{order_time.timestamp()}"
    
    coverage_type = drug_type.value
    
    # Set up the order data based on drug type
    if coverage_type == 'XAN':
        order_data = {
            'user_id': user.id,
            'username': str(user),
            'coverage_type': coverage_type,
            'hours': duration,
            'xanax_reward': reward,
            'start_time': order_time.strftime('%Y-%m-%d %H:%M:%S')
        }
        details = f"{duration}H Xanax coverage ({reward} Xanax reward)"
    else:  # EXTC
        order_data = {
            'user_id': user.id,
            'username': str(user),
            'coverage_type': coverage_type,
            'jumps': duration,
            'xanax_reward': reward,
            'ecstasy_reward': 1,  # Default values
            'edvds_reward': 3,    # Default values
            'start_time': order_time.strftime('%Y-%m-%d %H:%M:%S')
        }
        details = f"{duration} Jump Ecstasy coverage ({reward} Xanax reward)"
    
    # Store the order
    active_orders[order_id] = order_data
    
    # Create confirmation embed
    embed = discord.Embed(
        title="✅ Coverage Granted",
        description=f"Coverage has been given to {user.mention}",
        color=discord.Color.green()
    )
    embed.add_field(
        name="📋 Coverage Details",
        value=f"**Type:** {coverage_type}\n**Duration:** {duration} {'hours' if coverage_type == 'XAN' else 'jumps'}\n**Reward:** {reward} Xanax\n**Status:** Active",
        inline=False
    )
    embed.set_footer(text=f"Granted by: {interaction.user.display_name} | Order ID: {order_id}")
    
    await interaction.response.send_message(embed=embed)
    
    # Log in order channel
    order_channel = discord.utils.get(interaction.guild.channels, name="order")
    if order_channel:
        log_embed = discord.Embed(
            title="✅ Admin Coverage Grant",
            description=f"Coverage has been given to {user.mention} by {interaction.user.mention}",
            color=discord.Color.green()
        )
        log_embed.add_field(
            name="Coverage Details",
            value=details,
            inline=False
        )
        log_embed.set_footer(text=f"Order ID: {order_id}")
        await order_channel.send(embed=log_embed)

@bot.tree.command(name="del", description="Delete a specific pending order or overdose report (Admin only)")
@app_commands.describe(
    user="User whose order/report to delete",
    type="Type to delete: 'order' for pending orders, 'od' for overdose reports",
    order_number="Order number to delete (leave empty to see list first)"
)
@app_commands.choices(type=[
    app_commands.Choice(name="Pending Order", value="order"),
    app_commands.Choice(name="Overdose Report", value="od")
])
async def delete_entry(interaction: discord.Interaction, user: discord.Member, type: app_commands.Choice[str], order_number: int = None):
    """Delete a specific pending order or overdose report"""
    
    # Check if user is admin or in order channel
    if not interaction.user.guild_permissions.administrator and interaction.channel.name != "order":
        await interaction.response.send_message("❌ Only administrators or users in order channel can delete entries.", ephemeral=True)
        return
    
    delete_type = type.value
    
    if delete_type == "order":
        # Find pending orders for the user
        user_orders = [(order_id, data) for order_id, data in pending_order.items() if data.get('user_id') == user.id]
        
        if not user_orders:
            await interaction.response.send_message(f"❌ No pending orders found for {user.mention}.", ephemeral=True)
            return
        
        # If no specific order number provided, show list of orders
        if order_number is None:
            embed = discord.Embed(
                title="📋 Pending Orders List",
                description=f"Select which order to delete for {user.mention}",
                color=discord.Color.blue()
            )
            
            order_list = ""
            for i, (order_id, order_data) in enumerate(user_orders, 1):
                coverage_type = order_data.get('coverage_type', 'XAN')
                display_name = order_data.get('display_name', order_data.get('username', 'Unknown'))
                timestamp = order_data.get('timestamp', 'Unknown time')
                
                if coverage_type == 'XAN':
                    hours = order_data.get('hours', 24)
                    payment = order_data.get('xanax_payment', 0)
                    details = f"{hours}H Xanax coverage ({payment} Xanax payment)"
                else:
                    jumps = order_data.get('jumps', 1)
                    payment = order_data.get('xanax_payment', 0)
                    details = f"{jumps} Jump Ecstasy coverage ({payment} Xanax payment)"
                
                order_list += f"**{i}.** {details}\n   └ Created: {timestamp}\n   └ Order ID: `{order_id}`\n\n"
            
            embed.add_field(
                name="Available Orders",
                value=order_list[:1024],  # Discord field limit
                inline=False
            )
            embed.add_field(
                name="How to Delete",
                value=f"Use: `/del user:{user.mention} type:Pending Order order_number:[1-{len(user_orders)}]`",
                inline=False
            )
            embed.set_footer(text=f"Total orders: {len(user_orders)}")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Validate order number
        if order_number < 1 or order_number > len(user_orders):
            await interaction.response.send_message(
                f"❌ Invalid order number. Please choose between 1 and {len(user_orders)}.", 
                ephemeral=True
            )
            return
        
        # Delete the specific order
        selected_order = user_orders[order_number - 1]
        order_id, order_data = selected_order
        
        coverage_type = order_data.get('coverage_type', 'XAN')
        display_name = order_data.get('display_name', order_data.get('username', 'Unknown'))
        
        if coverage_type == 'XAN':
            hours = order_data.get('hours', 24)
            payment = order_data.get('xanax_payment', 0)
            details = f"{hours}H Xanax coverage ({payment} Xanax payment)"
        else:
            jumps = order_data.get('jumps', 1)
            payment = order_data.get('xanax_payment', 0)
            details = f"{jumps} Jump Ecstasy coverage ({payment} Xanax payment)"
        
        # Delete the order
        del pending_order[order_id]
        
        embed = discord.Embed(
            title="🗑️ Pending Order Deleted",
            description=f"Deleted order #{order_number} for **{display_name}**",
            color=discord.Color.red()
        )
        embed.add_field(
            name="Deleted Order Details",
            value=f"• {details}\n• Order ID: `{order_id}`\n• Created: {order_data.get('timestamp', 'Unknown')}",
            inline=False
        )
        embed.set_footer(text=f"Deleted by: {interaction.user.display_name}")
        
    elif delete_type == "od":
        # Find overdose reports for the user
        user_reports = [(report_id, data) for report_id, data in overdose_reports.items() 
                       if data.get('user_id') == user.id and data.get('status') == 'pending']
        
        if not user_reports:
            await interaction.response.send_message(f"❌ No pending overdose reports found for {user.mention}.", ephemeral=True)
            return
        
        # If no specific order number provided, show list of reports
        if order_number is None:
            embed = discord.Embed(
                title="📋 Overdose Reports List",
                description=f"Select which report to delete for {user.mention}",
                color=discord.Color.blue()
            )
            
            report_list = ""
            for i, (report_id, report_data) in enumerate(user_reports, 1):
                coverage_type = report_data.get('coverage_type', 'XAN')
                display_name = report_data.get('display_name', report_data.get('username', 'Unknown'))
                payout_details = report_data.get('payout_details', 'Unknown')
                timestamp = report_data.get('timestamp', 'Unknown time')
                
                report_list += f"**{i}.** {coverage_type}: {payout_details}\n   └ Reported: {timestamp}\n   └ Report ID: `{report_id}`\n\n"
            
            embed.add_field(
                name="Available Reports",
                value=report_list[:1024],  # Discord field limit
                inline=False
            )
            embed.add_field(
                name="How to Delete",
                value=f"Use: `/del user:{user.mention} type:Overdose Report order_number:[1-{len(user_reports)}]`",
                inline=False
            )
            embed.set_footer(text=f"Total reports: {len(user_reports)}")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Validate order number
        if order_number < 1 or order_number > len(user_reports):
            await interaction.response.send_message(
                f"❌ Invalid report number. Please choose between 1 and {len(user_reports)}.", 
                ephemeral=True
            )
            return
        
        # Delete the specific report
        selected_report = user_reports[order_number - 1]
        report_id, report_data = selected_report
        
        coverage_type = report_data.get('coverage_type', 'XAN')
        display_name = report_data.get('display_name', report_data.get('username', 'Unknown'))
        payout_details = report_data.get('payout_details', 'Unknown')
        
        # Delete the report
        del overdose_reports[report_id]
        
        embed = discord.Embed(
            title="🗑️ Overdose Report Deleted",
            description=f"Deleted report #{order_number} for **{display_name}**",
            color=discord.Color.red()
        )
        embed.add_field(
            name="Deleted Report Details",
            value=f"• {coverage_type}: {payout_details}\n• Report ID: `{report_id}`\n• Reported: {report_data.get('timestamp', 'Unknown')}",
            inline=False
        )
        embed.set_footer(text=f"Deleted by: {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed)
    
    # Log deletion to appropriate channel
    if delete_type == "order":
        log_channel = discord.utils.get(interaction.guild.channels, name="order")
    else:
        log_channel = discord.utils.get(interaction.guild.channels, name="payout")
    
    if log_channel:
        log_embed = discord.Embed(
            title="🗑️ Entry Deleted",
            description=f"{interaction.user.mention} deleted 1 {delete_type} for {user.mention}",
            color=discord.Color.orange()
        )
        log_embed.set_footer(text=f"Deleted at: {datetime.now().strftime('%m/%d %H:%M')}")
        try:
            await log_channel.send(embed=log_embed)
        except discord.Forbidden:
            print(f"⚠️  WARNING: Bot lacks permission to send to #{log_channel.name}")
        except Exception as e:
            print(f"⚠️  ERROR: Failed to log deletion to channel: {str(e)}")

@bot.tree.command(name="autocheck", description="Start automatic order checking (Admin only)")
@app_commands.describe(
    action="Action to perform",
    interval="Check interval in minutes (1-60, default 5)"
)
@app_commands.choices(action=[
    app_commands.Choice(name="Start", value="start"),
    app_commands.Choice(name="Stop", value="stop"),
    app_commands.Choice(name="Status", value="status")
])
async def auto_check_command(interaction: discord.Interaction, action: app_commands.Choice[str], interval: int = 5):
    """Control automatic order checking"""
    
    # Admin only check
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can control auto checking.", ephemeral=True)
        return
    
    global auto_check_enabled, auto_check_interval, last_check_time
    
    action_value = action.value
    
    if action_value == "start":
        # Check if API key is configured before starting auto-check
        torn_api_key = get_api_key()
        if not torn_api_key:
            await interaction.response.send_message("❌ Cannot start auto-check: Torn API key not configured! Use `/apikeyadd` to set it first.", ephemeral=True)
            return
            
        # Validate interval
        if interval < 1 or interval > 60:
            await interaction.response.send_message("❌ Interval must be between 1 and 60 minutes.", ephemeral=True)
            return
            
        auto_check_enabled = True
        auto_check_interval = interval
        last_check_time = datetime.now()
        
        # Start the task if not already running
        if not auto_check_orders.is_running():
            auto_check_orders.start()
            
        embed = discord.Embed(
            title="🔄 Auto Check Started",
            description="Automatic order checking is now enabled",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Settings",
            value=f"**Interval:** Every {interval} minute(s)\n**Features:**\n• Check existing pending orders\n• Detect new orders from Torn API\n• Auto-activate verified payments",
            inline=False
        )
        embed.set_footer(text=f"Started by: {interaction.user.display_name}")
        
    elif action_value == "stop":
        auto_check_enabled = False
        
        embed = discord.Embed(
            title="⏹️ Auto Check Stopped",
            description="Automatic order checking is now disabled",
            color=discord.Color.red()
        )
        embed.set_footer(text=f"Stopped by: {interaction.user.display_name}")
        
    elif action_value == "status":
        embed = discord.Embed(
            title="📊 Auto Check Status",
            color=discord.Color.blue()
        )
        
        status = "🟢 Enabled" if auto_check_enabled else "🔴 Disabled"
        next_check = "N/A" if not auto_check_enabled else f"<t:{int((last_check_time + timedelta(minutes=auto_check_interval)).timestamp())}:R>"
        
        embed.add_field(
            name="Current Status",
            value=f"**Status:** {status}\n**Interval:** {auto_check_interval} minute(s)\n**Next Check:** {next_check}",
            inline=False
        )
        
        embed.add_field(
            name="Statistics",
            value=f"**Pending Orders:** {len(pending_order)}\n**Active Orders:** {len(active_orders)}\n**Processed Events:** {len(processed_events)}",
            inline=False
        )
        
        embed.add_field(
            name="Features",
            value="• Verify existing pending orders\n• Detect new orders from Torn\n• Auto-match Discord users\n• Smart payment validation",
            inline=False
        )
        
        embed.set_footer(text=f"Last check: {last_check_time.strftime('%m/%d %H:%M')}")
    
    await interaction.response.send_message(embed=embed)

# Error handling
@bot.event
async def on_application_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"Command is on cooldown. Try again in {error.retry_after:.2f} seconds.",
            ephemeral=True
        )
    else:
        print(f"Error in command {interaction.command}: {error}")
        await interaction.response.send_message(
            "An error occurred while processing your command.",
            ephemeral=True
        )

# Run the bot
if __name__ == "__main__":
    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        print("Error: DISCORD_BOT_TOKEN not found in environment variables!")
        exit(1)
    
    bot.run(token)