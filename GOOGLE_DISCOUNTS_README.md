# Google Shopping Automated Discounts Integration

This implementation adds support for Google Shopping automated discounts using JWT token validation and price persistence.

## Features Implemented

### 1. JWT Token Validation (`app/utils.py`)
- Validates Google's ES256-signed JWT tokens
- Extracts discount information from token payload
- Validates merchant ID, expiration, and required fields
- Session-based discount persistence validation

### 2. Product Detail Page Integration (`app/main/routes.py`)
- Handles `pv2` URL parameter containing JWT token
- Validates token and stores discount info in session
- Passes discount information to template for display
- Maintains discount pricing across page navigation

### 3. Price Display (`app/templates/product_detail.html`)
- Shows Google discounted price when valid token present
- Displays "Google Special Price" indicator
- Falls back to regular 5% off pricing when no discount
- Updates JavaScript tracking with correct pricing

### 4. Cart Integration (`app/cart.py`)
- Accepts Google discount pricing from product detail form
- Stores discount metadata with cart items
- Maintains discount pricing for 48 hours as required
- Updates existing cart items with new discount pricing

### 5. Checkout Integration (`app/main/routes.py`)
- Honors Google discount pricing in checkout flow
- Maintains discount pricing throughout checkout process
- Supports both direct checkout and cart-based checkout

## Configuration

Add to your environment variables:
```bash
GOOGLE_MERCHANT_ID=140301646  # Your Google Merchant Center ID
```

## Usage

### Testing with Sample URLs
Google provides test URLs with valid JWT tokens. Example:
```
https://yourstore.com/product/your-product?pv2=eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Token Structure
The JWT token contains:
- `exp`: Expiration timestamp
- `o`: Offer ID (validates against product)
- `m`: Merchant ID (must match your GOOGLE_MERCHANT_ID)
- `p`: Google Automated Discount price
- `pp`: Prior price (optional)
- `c`: Currency code

### Price Persistence
- Discount prices persist for 30 minutes minimum (session-based)
- Cart items maintain discount pricing for 48 hours
- Discount validation includes expiration checks

## Testing

Run the test script to verify JWT validation:
```bash
python scripts/test_google_jwt.py
```

## Dependencies Added

- `PyJWT==2.8.0`: JWT token handling
- `cryptography==42.0.5`: Cryptographic operations for ES256

## Security Considerations

- JWT tokens are validated using Google's public key
- Merchant ID validation prevents token reuse across merchants
- Expiration validation prevents expired token usage
- Session-based storage limits exposure of sensitive data

## Google Requirements Compliance

✅ **Price Display**: Correct discounted price shown on product page  
✅ **Price Persistence**: Discount persists for 30+ minutes in session  
✅ **Cart Persistence**: Discount maintained for 48 hours in cart  
✅ **Checkout Persistence**: Discount maintained throughout checkout  
✅ **Token Validation**: Proper JWT validation with Google's public key  
✅ **Merchant Validation**: Merchant ID validation prevents cross-merchant usage  

## Next Steps

1. **Set GOOGLE_MERCHANT_ID** in your environment variables
2. **Test with Google's test URLs** when available
3. **Monitor Google Merchant Center** for automated discount approval
4. **Verify cart data integration** for Google Ads conversion tracking

## Troubleshooting

### Token Validation Fails
- Check that `GOOGLE_MERCHANT_ID` matches your Merchant Center ID
- Verify JWT dependencies are installed (`pip install PyJWT cryptography`)
- Check token expiration (tokens expire after 30 minutes)

### Discount Not Persisting
- Verify session storage is working
- Check that discount validation logic is running
- Ensure cart items include Google discount metadata

### Price Not Displaying
- Check that `google_discount_info` is passed to template
- Verify template conditional logic for discount display
- Check browser console for JavaScript errors
